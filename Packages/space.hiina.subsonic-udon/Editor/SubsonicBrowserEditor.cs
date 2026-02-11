using UnityEditor;
using UnityEngine;
using VRC.SDKBase;

namespace Hiinaspace.SubsonicUdon.Editor
{
    [CustomEditor(typeof(SubsonicBrowser))]
    public class SubsonicBrowserEditor : UnityEditor.Editor
    {
        string baseUrl = "http://localhost:8000";
        int slotCount = 1000;

        public override void OnInspectorGUI()
        {
            DrawDefaultInspector();

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Slot Generator", EditorStyles.boldLabel);

            baseUrl = EditorGUILayout.TextField("Base URL", baseUrl);
            slotCount = EditorGUILayout.IntField("Slot Count", slotCount);
            slotCount = Mathf.Max(1, slotCount);

            if (GUILayout.Button("Generate Slots"))
            {
                GenerateSlots();
            }

            if (GUILayout.Button("Validate Current Config"))
            {
                ValidateCurrentConfig();
            }
        }

        void GenerateSlots()
        {
            var so = serializedObject;
            string normalizedBaseUrl = NormalizeBaseUrl(baseUrl);

            // Set metadataUrl
            var metadataProp = so.FindProperty("metadataUrl");
            SetVRCUrl(metadataProp, $"{normalizedBaseUrl}/metadata.json");

            // Set slotUrls array
            var slotsProp = so.FindProperty("slotUrls");
            slotsProp.arraySize = slotCount;
            for (int i = 0; i < slotCount; i++)
            {
                string url = $"{normalizedBaseUrl}/{(i + 1):D4}.m3u8";
                SetVRCUrl(slotsProp.GetArrayElementAtIndex(i), url);
            }

            so.ApplyModifiedProperties();
            EditorUtility.SetDirty(target);
            AssetDatabase.SaveAssetIfDirty(target);
            Debug.Log($"[SubsonicBrowser] Generated {slotCount} slot URLs with base {normalizedBaseUrl}");
        }

        void ValidateCurrentConfig()
        {
            var browser = (SubsonicBrowser)target;
            if (browser == null)
            {
                Debug.LogError("[SubsonicBrowser] Validate failed: no target browser.");
                return;
            }

            string metadata = browser.metadataUrl != null ? browser.metadataUrl.Get() : string.Empty;
            int slotLen = browser.slotUrls != null ? browser.slotUrls.Length : 0;

            bool ok = true;
            if (string.IsNullOrWhiteSpace(metadata))
            {
                Debug.LogError("[SubsonicBrowser] Validate failed: metadataUrl is empty.");
                ok = false;
            }
            else if (!metadata.EndsWith("/metadata.json"))
            {
                Debug.LogWarning($"[SubsonicBrowser] metadataUrl does not end with /metadata.json: {metadata}");
            }

            if (slotLen <= 0)
            {
                Debug.LogError("[SubsonicBrowser] Validate failed: slotUrls is empty.");
                ok = false;
            }
            else
            {
                string firstSlot = browser.slotUrls[0] != null ? browser.slotUrls[0].Get() : string.Empty;
                string lastSlot = browser.slotUrls[slotLen - 1] != null ? browser.slotUrls[slotLen - 1].Get() : string.Empty;
                Debug.Log($"[SubsonicBrowser] slotUrls: {slotLen} entries, first={firstSlot}, last={lastSlot}");
            }

            if (ok)
            {
                Debug.Log("[SubsonicBrowser] Validate OK.");
            }
        }

        static void SetVRCUrl(SerializedProperty prop, string url)
        {
            // VRCUrl stores the URL string in a nested field called "url"
            var urlField = prop.FindPropertyRelative("url");
            if (urlField != null)
                urlField.stringValue = url;
        }

        static string NormalizeBaseUrl(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw)) return "http://localhost:8000";
            return raw.Trim().TrimEnd('/');
        }
    }
}
