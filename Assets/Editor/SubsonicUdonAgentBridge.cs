using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UdonSharp;
using UnityEditor;
using UnityEngine;

namespace SubsonicUdon.EditorBridge
{
    [InitializeOnLoad]
    internal static class SubsonicUdonAgentBridge
    {
        private const string AutoStartPref = "SubsonicUdon.AgentBridge.AutoStart";
        private const string HostPref = "SubsonicUdon.AgentBridge.Host";
        private const string PortPref = "SubsonicUdon.AgentBridge.Port";

        private static readonly object ListenerLock = new object();
        private static readonly object LogLock = new object();
        private static readonly Queue<Action> MainThreadQueue = new Queue<Action>();
        private static readonly object StateLock = new object();
        private static readonly object EvalLock = new object();

        private static HttpListener listener;
        private static CancellationTokenSource listenerCts;
        private static Task listenerTask;

        private static long nextLogId = 1;
        private static readonly List<BridgeLogEvent> logEvents = new List<BridgeLogEvent>(4096);
        private static CompileState cachedCompileState;
        private static readonly Dictionary<string, CSharpEvalJob> evalJobs = new Dictionary<string, CSharpEvalJob>();
        private static bool evalJobsLoaded;

        private const string EvalJobsFile = "Library/SubsonicUdonAgentBridge/eval-jobs.json";
        private const string EvalScriptDir = "Assets/Editor/SubsonicUdonAgentBridgeEval";
        private const string EvalScriptPath = EvalScriptDir + "/CurrentEvalJob.cs";
        private const string EvalScriptFileName = "CurrentEvalJob.cs";

        static SubsonicUdonAgentBridge()
        {
            Application.logMessageReceivedThreaded += OnLogMessageReceived;
            EditorApplication.update += PumpMainThreadQueue;
            EnsureEvalJobsLoaded();

            if (EditorPrefs.GetBool(AutoStartPref, true))
            {
                StartServer();
            }
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Start")]
        private static void MenuStart()
        {
            StartServer();
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Stop")]
        private static void MenuStop()
        {
            StopServer();
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Enable Auto Start")]
        private static void MenuEnableAutoStart()
        {
            EditorPrefs.SetBool(AutoStartPref, true);
            Debug.Log("[SubsonicUdonAgentBridge] Auto start enabled.");
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Disable Auto Start")]
        private static void MenuDisableAutoStart()
        {
            EditorPrefs.SetBool(AutoStartPref, false);
            Debug.Log("[SubsonicUdonAgentBridge] Auto start disabled.");
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Clear Captured Logs")]
        private static void MenuClearCapturedLogs()
        {
            lock (LogLock)
            {
                logEvents.Clear();
            }

            Debug.Log("[SubsonicUdonAgentBridge] Cleared in-memory bridge logs.");
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Start", true)]
        private static bool MenuStartValidate()
        {
            return !IsRunning;
        }

        [MenuItem("Tools/Subsonic Udon/Agent Bridge/Stop", true)]
        private static bool MenuStopValidate()
        {
            return IsRunning;
        }

        private static bool IsRunning
        {
            get
            {
                lock (ListenerLock)
                {
                    return listener != null && listener.IsListening;
                }
            }
        }

        private static void StartServer()
        {
            lock (ListenerLock)
            {
                if (listener != null && listener.IsListening)
                {
                    return;
                }

                string host = EditorPrefs.GetString(HostPref, "127.0.0.1");
                int port = EditorPrefs.GetInt(PortPref, 32190);

                string prefix = $"http://{host}:{port}/";

                listenerCts = new CancellationTokenSource();
                listener = new HttpListener();
                listener.Prefixes.Add(prefix);

                try
                {
                    listener.Start();
                }
                catch (Exception ex)
                {
                    listener = null;
                    listenerCts.Dispose();
                    listenerCts = null;
                    Debug.LogError($"[SubsonicUdonAgentBridge] Failed to start listener at {prefix}: {ex.Message}");
                    return;
                }

                listenerTask = Task.Run(() => ListenerLoopAsync(listenerCts.Token));
                Debug.Log($"[SubsonicUdonAgentBridge] Listening on {prefix}");
            }
        }

        private static void StopServer()
        {
            lock (ListenerLock)
            {
                if (listener == null)
                {
                    return;
                }

                try
                {
                    listenerCts.Cancel();
                }
                catch
                {
                    // Ignore cancellation edge cases.
                }

                try
                {
                    listener.Stop();
                    listener.Close();
                }
                catch
                {
                    // Ignore dispose edge cases.
                }

                listener = null;

                if (listenerCts != null)
                {
                    listenerCts.Dispose();
                    listenerCts = null;
                }

                listenerTask = null;
                Debug.Log("[SubsonicUdonAgentBridge] Listener stopped.");
            }
        }

        private static async Task ListenerLoopAsync(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                HttpListenerContext ctx = null;

                try
                {
                    ctx = await listener.GetContextAsync();
                }
                catch (ObjectDisposedException)
                {
                    break;
                }
                catch (HttpListenerException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[SubsonicUdonAgentBridge] Listener loop error: {ex.Message}");
                    await Task.Delay(100, token).ConfigureAwait(false);
                    continue;
                }

                _ = Task.Run(() => HandleRequestAsync(ctx), token);
            }
        }

        private static async Task HandleRequestAsync(HttpListenerContext ctx)
        {
            string method = ctx.Request.HttpMethod ?? string.Empty;
            string path = ctx.Request.Url != null ? ctx.Request.Url.AbsolutePath : string.Empty;

            try
            {
                if (string.Equals(path, "/health", StringComparison.OrdinalIgnoreCase))
                {
                    if (!string.Equals(method, "GET", StringComparison.OrdinalIgnoreCase) &&
                        !string.Equals(method, "POST", StringComparison.OrdinalIgnoreCase))
                    {
                        await WriteJsonAsync(ctx.Response, 405, new ErrorResponse { ok = false, error = "Only GET/POST is supported for /health." });
                        return;
                    }

                    await HandleHealthAsync(ctx.Response);
                    return;
                }

                if (!string.Equals(method, "POST", StringComparison.OrdinalIgnoreCase))
                {
                    await WriteJsonAsync(ctx.Response, 405, new ErrorResponse { ok = false, error = "Only POST is supported." });
                    return;
                }

                if (string.Equals(path, "/did-it-work", StringComparison.OrdinalIgnoreCase))
                {
                    string body = await ReadBodyAsync(ctx.Request);
                    DidItWorkRequest request = ParseJsonOrDefault<DidItWorkRequest>(body);
                    await HandleDidItWorkAsync(ctx.Response, request);
                    return;
                }

                if (string.Equals(path, "/logs/since", StringComparison.OrdinalIgnoreCase))
                {
                    string body = await ReadBodyAsync(ctx.Request);
                    LogsSinceRequest request = ParseJsonOrDefault<LogsSinceRequest>(body);
                    await HandleLogsSinceAsync(ctx.Response, request);
                    return;
                }

                if (string.Equals(path, "/udonsharp/create-script", StringComparison.OrdinalIgnoreCase))
                {
                    string body = await ReadBodyAsync(ctx.Request);
                    CreateUdonSharpScriptRequest request = ParseJsonOrDefault<CreateUdonSharpScriptRequest>(body);
                    await HandleCreateUdonSharpScriptAsync(ctx.Response, request);
                    return;
                }

                if (string.Equals(path, "/csharp/submit", StringComparison.OrdinalIgnoreCase))
                {
                    string body = await ReadBodyAsync(ctx.Request);
                    CSharpSubmitRequest request = ParseJsonOrDefault<CSharpSubmitRequest>(body);
                    await HandleCSharpSubmitAsync(ctx.Response, request);
                    return;
                }

                if (string.Equals(path, "/csharp/job", StringComparison.OrdinalIgnoreCase))
                {
                    string body = await ReadBodyAsync(ctx.Request);
                    CSharpJobRequest request = ParseJsonOrDefault<CSharpJobRequest>(body);
                    await HandleCSharpJobAsync(ctx.Response, request);
                    return;
                }

                await WriteJsonAsync(ctx.Response, 404, new ErrorResponse { ok = false, error = $"Unknown endpoint: {path}" });
            }
            catch (Exception ex)
            {
                await WriteJsonAsync(ctx.Response, 500, new ErrorResponse { ok = false, error = ex.ToString() });
            }
        }

        private static async Task HandleHealthAsync(HttpListenerResponse response)
        {
            CompileState state = BuildCompileState();
            HealthResponse payload = new HealthResponse
            {
                ok = true,
                isCompiling = state.isCompiling,
                isUpdating = state.isUpdating,
                isPlaying = state.isPlaying,
                logCount = GetLogCount(),
                lastLogId = GetLastLogId(),
            };

            await WriteJsonAsync(response, 200, payload);
        }

        private static async Task HandleDidItWorkAsync(HttpListenerResponse response, DidItWorkRequest request)
        {
            long beforeId = GetLastLogId();

            await ExecuteOnMainThreadAsync(() =>
            {
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            });

            int settleMs = request != null && request.settleMs > 0 ? request.settleMs : 500;
            int timeoutMs = request != null && request.timeoutMs > 0 ? request.timeoutMs : 15000;
            await WaitForEditorSettledAsync(timeoutMs, settleMs);

            long afterId = GetLastLogId();
            int maxGroups = request != null && request.maxGroups > 0 ? request.maxGroups : 200;
            CoalescedLog[] logs = GetCoalescedLogsSince(beforeId, maxGroups);

            DidItWorkResponse payload = new DidItWorkResponse
            {
                ok = true,
                beforeId = beforeId,
                afterId = afterId,
                newLogGroups = logs,
                compileState = BuildCompileState(),
            };

            await WriteJsonAsync(response, 200, payload);
        }

        private static async Task HandleLogsSinceAsync(HttpListenerResponse response, LogsSinceRequest request)
        {
            long sinceId = request != null ? request.sinceId : 0;
            int maxGroups = request != null && request.maxGroups > 0 ? request.maxGroups : 200;
            CoalescedLog[] logs = GetCoalescedLogsSince(sinceId, maxGroups);

            LogsSinceResponse payload = new LogsSinceResponse
            {
                ok = true,
                sinceId = sinceId,
                lastLogId = GetLastLogId(),
                logGroups = logs,
                compileState = BuildCompileState(),
            };

            await WriteJsonAsync(response, 200, payload);
        }

        private static async Task HandleCreateUdonSharpScriptAsync(HttpListenerResponse response, CreateUdonSharpScriptRequest request)
        {
            if (request == null || string.IsNullOrWhiteSpace(request.path))
            {
                await WriteJsonAsync(response, 400, new ErrorResponse { ok = false, error = "Missing required field: path" });
                return;
            }

            CreateUdonSharpScriptResult result = await ExecuteOnMainThreadAsync(() => CreateUdonSharpScript(request));
            int status = result.ok ? 200 : 400;
            await WriteJsonAsync(response, status, result);
        }

        private static async Task HandleCSharpSubmitAsync(HttpListenerResponse response, CSharpSubmitRequest request)
        {
            if (request == null || string.IsNullOrWhiteSpace(request.code))
            {
                await WriteJsonAsync(response, 400, new ErrorResponse { ok = false, error = "Missing required field: code" });
                return;
            }

            CSharpSubmitResult result = await ExecuteOnMainThreadAsync(() => SubmitCSharpJob(request));
            await WriteJsonAsync(response, result.ok ? 200 : 400, result);
        }

        private static async Task HandleCSharpJobAsync(HttpListenerResponse response, CSharpJobRequest request)
        {
            if (request == null || string.IsNullOrWhiteSpace(request.jobId))
            {
                await WriteJsonAsync(response, 400, new ErrorResponse { ok = false, error = "Missing required field: jobId" });
                return;
            }

            CSharpJobResult result = await ExecuteOnMainThreadAsync(() => GetCSharpJob(request.jobId));
            await WriteJsonAsync(response, result.ok ? 200 : 404, result);
        }

        private static CreateUdonSharpScriptResult CreateUdonSharpScript(CreateUdonSharpScriptRequest request)
        {
            try
            {
                string assetPath = ResolveAssetPath(request.path);
                if (!assetPath.EndsWith(".cs", StringComparison.OrdinalIgnoreCase))
                {
                    assetPath += ".cs";
                }

                string assetDir = Path.GetDirectoryName(assetPath).Replace('\\', '/');
                if (!assetDir.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase) &&
                    !assetDir.StartsWith("Packages/", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(assetDir, "Assets", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(assetDir, "Packages", StringComparison.OrdinalIgnoreCase))
                {
                    return new CreateUdonSharpScriptResult { ok = false, error = "Script path must be under Assets/ or Packages/." };
                }

                string fileNameRaw = Path.GetFileNameWithoutExtension(assetPath);
                string className = SanitizeName(fileNameRaw);
                string sanitizedPath = assetDir + "/" + className + ".cs";
                string programAssetPath = assetDir + "/" + className + ".asset";

                bool overwrite = request.overwrite;

                if (!overwrite)
                {
                    if (File.Exists(ToAbsolutePath(sanitizedPath)))
                    {
                        return new CreateUdonSharpScriptResult { ok = false, error = $"Script already exists: {sanitizedPath}" };
                    }

                    if (AssetDatabase.LoadAssetAtPath<UdonSharpProgramAsset>(programAssetPath) != null)
                    {
                        return new CreateUdonSharpScriptResult { ok = false, error = $"Program asset already exists: {programAssetPath}" };
                    }
                }

                string absoluteScriptPath = ToAbsolutePath(sanitizedPath);
                string absoluteDir = Path.GetDirectoryName(absoluteScriptPath);
                if (!Directory.Exists(absoluteDir))
                {
                    Directory.CreateDirectory(absoluteDir);
                }

                string fileContents = string.IsNullOrWhiteSpace(request.contents)
                    ? BuildDefaultTemplate(className)
                    : request.contents.Replace("<TemplateClassName>", className);

                File.WriteAllText(absoluteScriptPath, fileContents, new UTF8Encoding(false));

                AssetDatabase.ImportAsset(sanitizedPath, ImportAssetOptions.ForceSynchronousImport);
                MonoScript script = AssetDatabase.LoadAssetAtPath<MonoScript>(sanitizedPath);
                if (script == null)
                {
                    return new CreateUdonSharpScriptResult { ok = false, error = $"Failed to import script at {sanitizedPath}" };
                }

                if (overwrite)
                {
                    AssetDatabase.DeleteAsset(programAssetPath);
                }

                UdonSharpProgramAsset programAsset = ScriptableObject.CreateInstance<UdonSharpProgramAsset>();
                programAsset.sourceCsScript = script;
                AssetDatabase.CreateAsset(programAsset, programAssetPath);
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

                return new CreateUdonSharpScriptResult
                {
                    ok = true,
                    scriptPath = sanitizedPath,
                    programAssetPath = programAssetPath,
                    className = className,
                    lastLogId = GetLastLogId(),
                };
            }
            catch (Exception ex)
            {
                return new CreateUdonSharpScriptResult { ok = false, error = ex.ToString() };
            }
        }

        private static CSharpSubmitResult SubmitCSharpJob(CSharpSubmitRequest request)
        {
            EnsureEvalJobsLoaded();

            lock (EvalLock)
            {
                CSharpEvalJob active = evalJobs.Values.FirstOrDefault(j => j.status == "queued" || j.status == "running");
                if (active != null)
                {
                    return new CSharpSubmitResult
                    {
                        ok = false,
                        error = $"A job is already active ({active.jobId}, status={active.status}). Poll /csharp/job first.",
                    };
                }

                string jobId = $"job_{DateTime.UtcNow.Ticks}";
                int timeoutMs = request.timeoutMs > 0 ? request.timeoutMs : 30000;
                long beforeLogId = GetLastLogId();
                string scriptContents = BuildEvalRunnerScript(jobId, request.code, request.usings);

                try
                {
                    Directory.CreateDirectory(ToAbsolutePath(EvalScriptDir));
                    File.WriteAllText(ToAbsolutePath(EvalScriptPath), scriptContents, new UTF8Encoding(false));
                    AssetDatabase.ImportAsset(EvalScriptPath, ImportAssetOptions.ForceSynchronousImport);
                }
                catch (Exception ex)
                {
                    return new CSharpSubmitResult
                    {
                        ok = false,
                        error = $"Failed to write eval runner script: {ex.Message}",
                    };
                }

                CSharpEvalJob job = new CSharpEvalJob
                {
                    jobId = jobId,
                    status = "queued",
                    code = request.code,
                    scriptPath = EvalScriptPath,
                    timeoutMs = timeoutMs,
                    beforeLogId = beforeLogId,
                    submittedUtc = DateTime.UtcNow.ToString("o"),
                    updatedUtc = DateTime.UtcNow.ToString("o"),
                };

                evalJobs[jobId] = job;
                SaveEvalJobs();

                return new CSharpSubmitResult
                {
                    ok = true,
                    jobId = job.jobId,
                    status = job.status,
                    scriptPath = job.scriptPath,
                    beforeLogId = job.beforeLogId,
                    timeoutMs = job.timeoutMs,
                };
            }
        }

        private static CSharpJobResult GetCSharpJob(string jobId)
        {
            EnsureEvalJobsLoaded();

            lock (EvalLock)
            {
                if (!evalJobs.TryGetValue(jobId, out CSharpEvalJob job))
                {
                    return new CSharpJobResult { ok = false, error = $"Job not found: {jobId}" };
                }

                MaybeResolveQueuedJobFromLogs(job);
                MaybeTimeoutJob(job);
                SaveEvalJobs();

                return new CSharpJobResult
                {
                    ok = true,
                    job = job.Clone(),
                };
            }
        }

        internal static bool TryStartEvalJob(string jobId)
        {
            EnsureEvalJobsLoaded();

            lock (EvalLock)
            {
                if (!evalJobs.TryGetValue(jobId, out CSharpEvalJob job))
                {
                    return false;
                }

                if (job.status != "queued")
                {
                    return false;
                }

                job.status = "running";
                job.startedUtc = DateTime.UtcNow.ToString("o");
                job.updatedUtc = DateTime.UtcNow.ToString("o");
                SaveEvalJobs();
                return true;
            }
        }

        internal static long GetLastLogIdForEval()
        {
            return GetLastLogId();
        }

        internal static void CompleteEvalJobSuccess(string jobId, object result, long beforeLogId, long afterLogId)
        {
            EnsureEvalJobsLoaded();

            lock (EvalLock)
            {
                if (!evalJobs.TryGetValue(jobId, out CSharpEvalJob job))
                {
                    return;
                }

                job.status = "succeeded";
                job.result = result != null ? result.ToString() : string.Empty;
                job.resultType = result != null ? result.GetType().FullName : "null";
                job.beforeLogId = beforeLogId;
                job.afterLogId = afterLogId;
                job.finishedUtc = DateTime.UtcNow.ToString("o");
                job.updatedUtc = DateTime.UtcNow.ToString("o");
                SaveEvalJobs();
            }
        }

        internal static void CompleteEvalJobFailure(string jobId, string error, long beforeLogId, long afterLogId)
        {
            EnsureEvalJobsLoaded();

            lock (EvalLock)
            {
                if (!evalJobs.TryGetValue(jobId, out CSharpEvalJob job))
                {
                    return;
                }

                job.status = "failed";
                job.error = error ?? "Unknown error";
                job.beforeLogId = beforeLogId;
                job.afterLogId = afterLogId;
                job.finishedUtc = DateTime.UtcNow.ToString("o");
                job.updatedUtc = DateTime.UtcNow.ToString("o");
                SaveEvalJobs();
            }
        }

        private static void MaybeResolveQueuedJobFromLogs(CSharpEvalJob job)
        {
            if (job.status != "queued")
            {
                return;
            }

            CompileState state = BuildCompileState();
            if (state.isCompiling || state.isUpdating)
            {
                return;
            }

            CoalescedLog[] logs = GetCoalescedLogsSince(job.beforeLogId, 500);
            List<string> compileErrors = new List<string>();
            for (int i = 0; i < logs.Length; i++)
            {
                CoalescedLog log = logs[i];
                if (!string.Equals(log.type, "Error", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                string msg = log.fullMessage ?? log.message ?? string.Empty;
                if (msg.IndexOf(EvalScriptFileName, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    compileErrors.Add(msg);
                }
            }

            if (compileErrors.Count > 0)
            {
                job.status = "failed_compile";
                job.error = string.Join("\n", compileErrors.ToArray());
                job.afterLogId = GetLastLogId();
                job.finishedUtc = DateTime.UtcNow.ToString("o");
                job.updatedUtc = DateTime.UtcNow.ToString("o");
            }
        }

        private static void MaybeTimeoutJob(CSharpEvalJob job)
        {
            if (job.status != "queued" && job.status != "running")
            {
                return;
            }

            if (!DateTime.TryParse(job.submittedUtc, out DateTime submitted))
            {
                return;
            }

            double elapsedMs = (DateTime.UtcNow - submitted.ToUniversalTime()).TotalMilliseconds;
            if (elapsedMs < job.timeoutMs)
            {
                return;
            }

            job.status = "timeout";
            job.error = $"Job timed out after {job.timeoutMs}ms.";
            job.afterLogId = GetLastLogId();
            job.finishedUtc = DateTime.UtcNow.ToString("o");
            job.updatedUtc = DateTime.UtcNow.ToString("o");
        }

        private static string BuildEvalRunnerScript(string jobId, string userCode, string[] extraUsings)
        {
            StringBuilder usingBuilder = new StringBuilder();
            usingBuilder.AppendLine("using System;");
            usingBuilder.AppendLine("using UnityEditor;");
            usingBuilder.AppendLine("using UnityEngine;");
            usingBuilder.AppendLine("using SubsonicUdon.EditorBridge;");

            if (extraUsings != null)
            {
                for (int i = 0; i < extraUsings.Length; i++)
                {
                    string ns = (extraUsings[i] ?? string.Empty).Trim();
                    if (string.IsNullOrEmpty(ns))
                    {
                        continue;
                    }

                    usingBuilder.Append("using ");
                    usingBuilder.Append(ns);
                    usingBuilder.AppendLine(";");
                }
            }

            string safeCode = userCode ?? string.Empty;
            if (!safeCode.EndsWith("\n", StringComparison.Ordinal))
            {
                safeCode += "\n";
            }

            return
usingBuilder.ToString() +
"\n" +
"namespace SubsonicUdon.EditorBridge\n" +
"{\n" +
"    [InitializeOnLoad]\n" +
"    internal static class CurrentEvalJobRunner\n" +
"    {\n" +
"        static CurrentEvalJobRunner()\n" +
"        {\n" +
"            EditorApplication.delayCall += Run;\n" +
"        }\n" +
"\n" +
"        private static void Run()\n" +
"        {\n" +
$"            const string jobId = \"{jobId}\";\n" +
"            if (!SubsonicUdonAgentBridge.TryStartEvalJob(jobId))\n" +
"            {\n" +
"                return;\n" +
"            }\n" +
"\n" +
"            long before = SubsonicUdonAgentBridge.GetLastLogIdForEval();\n" +
"            try\n" +
"            {\n" +
"                object result = ((Func<object>)(() =>\n" +
"                {\n" +
safeCode +
"                    return null;\n" +
"                }))();\n" +
"\n" +
"                long after = SubsonicUdonAgentBridge.GetLastLogIdForEval();\n" +
"                SubsonicUdonAgentBridge.CompleteEvalJobSuccess(jobId, result, before, after);\n" +
"            }\n" +
"            catch (Exception ex)\n" +
"            {\n" +
"                long after = SubsonicUdonAgentBridge.GetLastLogIdForEval();\n" +
"                SubsonicUdonAgentBridge.CompleteEvalJobFailure(jobId, ex.ToString(), before, after);\n" +
"            }\n" +
"        }\n" +
"    }\n" +
"}\n";
        }

        private static void EnsureEvalJobsLoaded()
        {
            lock (EvalLock)
            {
                if (evalJobsLoaded)
                {
                    return;
                }

                evalJobs.Clear();
                string path = ToAbsolutePath(EvalJobsFile);
                if (File.Exists(path))
                {
                    try
                    {
                        string json = File.ReadAllText(path);
                        CSharpEvalJobStore store = JsonUtility.FromJson<CSharpEvalJobStore>(json);
                        if (store != null && store.jobs != null)
                        {
                            for (int i = 0; i < store.jobs.Length; i++)
                            {
                                CSharpEvalJob job = store.jobs[i];
                                if (job == null || string.IsNullOrEmpty(job.jobId))
                                {
                                    continue;
                                }

                                evalJobs[job.jobId] = job;
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Debug.LogWarning($"[SubsonicUdonAgentBridge] Failed to load eval jobs: {ex.Message}");
                    }
                }

                evalJobsLoaded = true;
            }
        }

        private static void SaveEvalJobs()
        {
            CSharpEvalJobStore store = new CSharpEvalJobStore
            {
                jobs = evalJobs.Values.ToArray(),
            };

            string json = JsonUtility.ToJson(store, true);
            string path = ToAbsolutePath(EvalJobsFile);
            string dir = Path.GetDirectoryName(path);
            if (!Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            File.WriteAllText(path, json, new UTF8Encoding(false));
        }

        private static CompileState BuildCompileState()
        {
            lock (StateLock)
            {
                return cachedCompileState;
            }
        }

        private static string BuildDefaultTemplate(string className)
        {
            return
$"using UdonSharp;\n" +
"using UnityEngine;\n" +
"using VRC.SDKBase;\n" +
"using VRC.Udon;\n\n" +
$"public class {className} : UdonSharpBehaviour\n" +
"{\n" +
"    void Start()\n" +
"    {\n" +
"    }\n" +
"}\n";
        }

        private static string ResolveAssetPath(string inputPath)
        {
            string normalized = inputPath.Replace('\\', '/').Trim();
            if (normalized.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase) ||
                normalized.StartsWith("Packages/", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(normalized, "Assets", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(normalized, "Packages", StringComparison.OrdinalIgnoreCase))
            {
                return normalized;
            }

            string fullPath = normalized;
            if (!Path.IsPathRooted(fullPath))
            {
                fullPath = Path.GetFullPath(Path.Combine(ProjectRoot(), normalized));
            }

            string root = ProjectRoot().Replace('\\', '/');
            string fullNormalized = fullPath.Replace('\\', '/');
            if (!fullNormalized.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Path must be inside the Unity project.");
            }

            string relative = fullNormalized.Substring(root.Length).TrimStart('/');
            return relative;
        }

        private static string ToAbsolutePath(string assetPath)
        {
            return Path.Combine(ProjectRoot(), assetPath).Replace('\\', '/');
        }

        private static string ProjectRoot()
        {
            return Path.GetDirectoryName(Application.dataPath).Replace('\\', '/');
        }

        private static string SanitizeName(string name)
        {
            return name.Replace(" ", "")
                       .Replace("#", "Sharp")
                       .Replace("(", "")
                       .Replace(")", "")
                       .Replace("*", "")
                       .Replace("<", "")
                       .Replace(">", "")
                       .Replace("-", "_")
                       .Replace("!", "")
                       .Replace("$", "")
                       .Replace("@", "")
                       .Replace("+", "");
        }

        private static async Task WaitForEditorSettledAsync(int timeoutMs, int settleMs)
        {
            DateTime deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            DateTime? stableSince = null;

            while (DateTime.UtcNow < deadline)
            {
                CompileState state = BuildCompileState();
                bool stable = !state.isCompiling && !state.isUpdating;
                if (stable)
                {
                    if (!stableSince.HasValue)
                    {
                        stableSince = DateTime.UtcNow;
                    }

                    if ((DateTime.UtcNow - stableSince.Value).TotalMilliseconds >= settleMs)
                    {
                        return;
                    }
                }
                else
                {
                    stableSince = null;
                }

                await Task.Delay(100).ConfigureAwait(false);
            }
        }

        private static void OnLogMessageReceived(string condition, string stackTrace, LogType type)
        {
            lock (LogLock)
            {
                logEvents.Add(new BridgeLogEvent
                {
                    id = nextLogId++,
                    type = type.ToString(),
                    message = condition ?? string.Empty,
                    stackTrace = stackTrace ?? string.Empty,
                    timestampUtc = DateTime.UtcNow.ToString("o"),
                });

                const int maxEvents = 5000;
                if (logEvents.Count > maxEvents)
                {
                    int removeCount = logEvents.Count - maxEvents;
                    logEvents.RemoveRange(0, removeCount);
                }
            }
        }

        private static int GetLogCount()
        {
            lock (LogLock)
            {
                return logEvents.Count;
            }
        }

        private static long GetLastLogId()
        {
            lock (LogLock)
            {
                if (logEvents.Count == 0)
                {
                    return 0;
                }

                return logEvents[logEvents.Count - 1].id;
            }
        }

        private static CoalescedLog[] GetCoalescedLogsSince(long sinceExclusive, int maxGroups)
        {
            List<BridgeLogEvent> snapshot = new List<BridgeLogEvent>();
            lock (LogLock)
            {
                for (int i = 0; i < logEvents.Count; i++)
                {
                    if (logEvents[i].id > sinceExclusive)
                    {
                        snapshot.Add(logEvents[i]);
                    }
                }
            }

            List<CoalescedLog> groups = new List<CoalescedLog>();
            Dictionary<string, int> keyToIndex = new Dictionary<string, int>();

            for (int i = 0; i < snapshot.Count; i++)
            {
                BridgeLogEvent e = snapshot[i];
                string firstLine = FirstLine(e.message);
                string key = e.type + "\n" + e.message + "\n" + e.stackTrace;

                int idx;
                if (keyToIndex.TryGetValue(key, out idx))
                {
                    CoalescedLog existing = groups[idx];
                    existing.count += 1;
                    existing.lastId = e.id;
                    existing.lastTimestampUtc = e.timestampUtc;
                    groups[idx] = existing;
                    continue;
                }

                CoalescedLog created = new CoalescedLog
                {
                    type = e.type,
                    message = firstLine,
                    fullMessage = e.message,
                    stackTrace = e.stackTrace,
                    count = 1,
                    firstId = e.id,
                    lastId = e.id,
                    firstTimestampUtc = e.timestampUtc,
                    lastTimestampUtc = e.timestampUtc,
                };

                keyToIndex[key] = groups.Count;
                groups.Add(created);

                if (groups.Count >= maxGroups)
                {
                    break;
                }
            }

            return groups.ToArray();
        }

        private static string FirstLine(string message)
        {
            if (string.IsNullOrEmpty(message))
            {
                return string.Empty;
            }

            int newline = message.IndexOf('\n');
            if (newline < 0)
            {
                return message;
            }

            return message.Substring(0, newline);
        }

        private static async Task<string> ReadBodyAsync(HttpListenerRequest request)
        {
            if (request == null || request.InputStream == null)
            {
                return string.Empty;
            }

            using (StreamReader reader = new StreamReader(request.InputStream, request.ContentEncoding ?? Encoding.UTF8))
            {
                return await reader.ReadToEndAsync();
            }
        }

        private static T ParseJsonOrDefault<T>(string json) where T : class, new()
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                return new T();
            }

            try
            {
                T parsed = JsonUtility.FromJson<T>(json);
                return parsed ?? new T();
            }
            catch
            {
                return new T();
            }
        }

        private static async Task WriteJsonAsync(HttpListenerResponse response, int statusCode, object payload)
        {
            response.StatusCode = statusCode;
            response.ContentType = "application/json";
            response.ContentEncoding = Encoding.UTF8;

            string json = JsonUtility.ToJson(payload, true);
            byte[] bytes = Encoding.UTF8.GetBytes(json);

            try
            {
                await response.OutputStream.WriteAsync(bytes, 0, bytes.Length);
            }
            finally
            {
                response.OutputStream.Close();
                response.Close();
            }
        }

        private static Task ExecuteOnMainThreadAsync(Action action)
        {
            TaskCompletionSource<bool> tcs = new TaskCompletionSource<bool>();

            lock (MainThreadQueue)
            {
                MainThreadQueue.Enqueue(() =>
                {
                    try
                    {
                        action();
                        tcs.TrySetResult(true);
                    }
                    catch (Exception ex)
                    {
                        tcs.TrySetException(ex);
                    }
                });
            }

            return tcs.Task;
        }

        private static Task<T> ExecuteOnMainThreadAsync<T>(Func<T> func)
        {
            TaskCompletionSource<T> tcs = new TaskCompletionSource<T>();

            lock (MainThreadQueue)
            {
                MainThreadQueue.Enqueue(() =>
                {
                    try
                    {
                        T result = func();
                        tcs.TrySetResult(result);
                    }
                    catch (Exception ex)
                    {
                        tcs.TrySetException(ex);
                    }
                });
            }

            return tcs.Task;
        }

        private static void PumpMainThreadQueue()
        {
            UpdateEditorStateCache();

            const int maxPerFrame = 32;
            int processed = 0;

            while (processed < maxPerFrame)
            {
                Action next = null;

                lock (MainThreadQueue)
                {
                    if (MainThreadQueue.Count > 0)
                    {
                        next = MainThreadQueue.Dequeue();
                    }
                }

                if (next == null)
                {
                    break;
                }

                next();
                processed += 1;
            }
        }

        private static void UpdateEditorStateCache()
        {
            lock (StateLock)
            {
                cachedCompileState = new CompileState
                {
                    isCompiling = EditorApplication.isCompiling,
                    isUpdating = EditorApplication.isUpdating,
                    isPlaying = EditorApplication.isPlaying,
                };
            }
        }

        [Serializable]
        private class DidItWorkRequest
        {
            public int settleMs;
            public int timeoutMs;
            public int maxGroups;
        }

        [Serializable]
        private class LogsSinceRequest
        {
            public long sinceId;
            public int maxGroups;
        }

        [Serializable]
        private class CreateUdonSharpScriptRequest
        {
            public string path;
            public bool overwrite;
            public string contents;
        }

        [Serializable]
        private class CSharpSubmitRequest
        {
            public string code;
            public int timeoutMs;
            public string[] usings;
        }

        [Serializable]
        private class CSharpJobRequest
        {
            public string jobId;
        }

        [Serializable]
        private class HealthResponse
        {
            public bool ok;
            public bool isCompiling;
            public bool isUpdating;
            public bool isPlaying;
            public int logCount;
            public long lastLogId;
        }

        [Serializable]
        private class DidItWorkResponse
        {
            public bool ok;
            public long beforeId;
            public long afterId;
            public CoalescedLog[] newLogGroups;
            public CompileState compileState;
        }

        [Serializable]
        private class LogsSinceResponse
        {
            public bool ok;
            public long sinceId;
            public long lastLogId;
            public CoalescedLog[] logGroups;
            public CompileState compileState;
        }

        [Serializable]
        private class CreateUdonSharpScriptResult
        {
            public bool ok;
            public string error;
            public string scriptPath;
            public string programAssetPath;
            public string className;
            public long lastLogId;
        }

        [Serializable]
        private class ErrorResponse
        {
            public bool ok;
            public string error;
        }

        [Serializable]
        private class CSharpSubmitResult
        {
            public bool ok;
            public string error;
            public string jobId;
            public string status;
            public string scriptPath;
            public long beforeLogId;
            public int timeoutMs;
        }

        [Serializable]
        private class CSharpJobResult
        {
            public bool ok;
            public string error;
            public CSharpEvalJob job;
        }

        [Serializable]
        private class CSharpEvalJobStore
        {
            public CSharpEvalJob[] jobs;
        }

        [Serializable]
        private class CSharpEvalJob
        {
            public string jobId;
            public string status;
            public string code;
            public string scriptPath;
            public int timeoutMs;
            public long beforeLogId;
            public long afterLogId;
            public string result;
            public string resultType;
            public string error;
            public string submittedUtc;
            public string startedUtc;
            public string finishedUtc;
            public string updatedUtc;

            public CSharpEvalJob Clone()
            {
                return new CSharpEvalJob
                {
                    jobId = jobId,
                    status = status,
                    code = code,
                    scriptPath = scriptPath,
                    timeoutMs = timeoutMs,
                    beforeLogId = beforeLogId,
                    afterLogId = afterLogId,
                    result = result,
                    resultType = resultType,
                    error = error,
                    submittedUtc = submittedUtc,
                    startedUtc = startedUtc,
                    finishedUtc = finishedUtc,
                    updatedUtc = updatedUtc,
                };
            }
        }

        [Serializable]
        private struct CompileState
        {
            public bool isCompiling;
            public bool isUpdating;
            public bool isPlaying;
        }

        [Serializable]
        private struct BridgeLogEvent
        {
            public long id;
            public string type;
            public string message;
            public string stackTrace;
            public string timestampUtc;
        }

        [Serializable]
        private struct CoalescedLog
        {
            public string type;
            public string message;
            public string fullMessage;
            public string stackTrace;
            public int count;
            public long firstId;
            public long lastId;
            public string firstTimestampUtc;
            public string lastTimestampUtc;
        }
    }
}
