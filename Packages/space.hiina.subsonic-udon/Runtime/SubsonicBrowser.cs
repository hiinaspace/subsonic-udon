using JLChnToZ.VRC.VVMW;
using UdonSharp;
using UnityEngine;
using VRC.SDK3.Data;
using VRC.SDK3.StringLoading;
using VRC.SDKBase;
using VRC.Udon.Common.Interfaces;

namespace Hiinaspace.SubsonicUdon
{
    [UdonBehaviourSyncMode(BehaviourSyncMode.None)]
    public class SubsonicBrowser : UdonSharpBehaviour
    {
        [Header("Configuration (set by editor script)")]
        public VRCUrl metadataUrl;
        public VRCUrl[] slotUrls;

        [Header("VizVid")]
        public FrontendHandler frontendHandler;
        public byte playerIndex = 1;
        public bool autoplayFirstTrackOnLoad = false;

        [Header("Runtime State (do not edit)")]
        [HideInInspector] public string[] trackIds;
        [HideInInspector] public string[] trackSlotIds;
        [HideInInspector] public string[] trackTitles;
        [HideInInspector] public string[] trackArtists;
        [HideInInspector] public string[] trackAlbums;
        [HideInInspector] public string[] trackAlbumIds;
        [HideInInspector] public int[] trackDurations;
        [HideInInspector] public int[] trackSlotIndices;
        [HideInInspector] public int trackCount;
        [HideInInspector] public int[] filteredTrackIndices;
        [HideInInspector] public int filteredTrackCount;
        [HideInInspector] public string currentSearchQuery;

        void Start()
        {
            VRCStringDownloader.LoadUrl(metadataUrl, (IUdonEventReceiver)this);
        }

        public override void OnStringLoadSuccess(IVRCStringDownload result)
        {
            if (TryParseMetadata(result.Result))
            {
                SetSearchQuery(string.Empty);
                Debug.Log($"[SubsonicBrowser] Metadata loaded: {trackCount} tracks.");

                if (autoplayFirstTrackOnLoad && trackCount > 0)
                {
                    PlayTrack(0);
                }
            }
            else
            {
                Debug.LogError("[SubsonicBrowser] Metadata parsing failed.");
            }
        }

        public override void OnStringLoadError(IVRCStringDownload result)
        {
            Debug.LogError($"[SubsonicBrowser] Failed to load metadata: {result.Error} (code {result.ErrorCode})");
        }

        public void SetSearchQuery(string query)
        {
            if (query == null) query = string.Empty;
            currentSearchQuery = query;

            if (trackCount <= 0)
            {
                filteredTrackIndices = new int[0];
                filteredTrackCount = 0;
                return;
            }

            if (filteredTrackIndices == null || filteredTrackIndices.Length != trackCount)
                filteredTrackIndices = new int[trackCount];

            string lowered = query.ToLowerInvariant();
            int outCount = 0;
            for (int i = 0; i < trackCount; i++)
            {
                if (MatchesQuery(i, lowered))
                {
                    filteredTrackIndices[outCount] = i;
                    outCount++;
                }
            }
            filteredTrackCount = outCount;
        }

        public void PlayFiltered(int filteredIndex)
        {
            if (filteredIndex < 0 || filteredIndex >= filteredTrackCount) return;
            PlayTrack(filteredTrackIndices[filteredIndex]);
        }

        public void PlayTrack(int trackIndex)
        {
            if (trackIndex < 0 || trackIndex >= trackCount) return;
            if (frontendHandler == null || slotUrls == null) return;

            int slotIndex = trackSlotIndices[trackIndex];
            if (slotIndex < 0 || slotIndex >= slotUrls.Length) return;

            VRCUrl url = slotUrls[slotIndex];
            string title = trackTitles[trackIndex];
            frontendHandler.PlayUrl(url, url, title, playerIndex);
        }

        bool MatchesQuery(int trackIndex, string loweredQuery)
        {
            if (string.IsNullOrEmpty(loweredQuery)) return true;

            string title = trackTitles[trackIndex];
            if (!string.IsNullOrEmpty(title) && title.ToLowerInvariant().Contains(loweredQuery)) return true;

            string artist = trackArtists[trackIndex];
            if (!string.IsNullOrEmpty(artist) && artist.ToLowerInvariant().Contains(loweredQuery)) return true;

            string album = trackAlbums[trackIndex];
            if (!string.IsNullOrEmpty(album) && album.ToLowerInvariant().Contains(loweredQuery)) return true;

            return false;
        }

        bool TryParseMetadata(string rawJson)
        {
            if (string.IsNullOrEmpty(rawJson))
            {
                Debug.LogError("[SubsonicBrowser] Metadata payload was empty.");
                return false;
            }

            DataToken rootToken;
            if (!VRCJson.TryDeserializeFromJson(rawJson, out rootToken))
            {
                Debug.LogError("[SubsonicBrowser] JSON deserialization failed.");
                return false;
            }
            if (rootToken.TokenType != TokenType.DataDictionary)
            {
                Debug.LogError($"[SubsonicBrowser] Expected root object, got {rootToken.TokenType}.");
                return false;
            }

            DataDictionary root = rootToken.DataDictionary;
            DataToken tracksToken;
            if (!root.TryGetValue("tracks", out tracksToken) || tracksToken.TokenType != TokenType.DataDictionary)
            {
                Debug.LogError("[SubsonicBrowser] Missing or invalid tracks object.");
                return false;
            }

            DataDictionary tracksDict = tracksToken.DataDictionary;
            DataList slotKeys = tracksDict.GetKeys();
            int maxTracks = slotKeys.Count;
            if (maxTracks <= 0)
            {
                trackIds = new string[0];
                trackSlotIds = new string[0];
                trackTitles = new string[0];
                trackArtists = new string[0];
                trackAlbums = new string[0];
                trackAlbumIds = new string[0];
                trackDurations = new int[0];
                trackSlotIndices = new int[0];
                trackCount = 0;
                return true;
            }

            trackIds = new string[maxTracks];
            trackSlotIds = new string[maxTracks];
            trackTitles = new string[maxTracks];
            trackArtists = new string[maxTracks];
            trackAlbums = new string[maxTracks];
            trackAlbumIds = new string[maxTracks];
            trackDurations = new int[maxTracks];
            trackSlotIndices = new int[maxTracks];
            trackCount = 0;

            for (int i = 0; i < maxTracks; i++)
            {
                string slotId = slotKeys[i].ToString();
                int slotIndex = SlotIdToIndex(slotId);
                if (slotIndex < 0 || slotUrls == null || slotIndex >= slotUrls.Length) continue;

                DataToken trackToken;
                if (!tracksDict.TryGetValue(slotId, out trackToken) || trackToken.TokenType != TokenType.DataDictionary)
                    continue;

                DataDictionary trackDict = trackToken.DataDictionary;
                int writeIndex = FindInsertIndex(slotIndex);
                ShiftRightFrom(writeIndex);

                trackSlotIndices[writeIndex] = slotIndex;
                trackSlotIds[writeIndex] = slotId;
                trackIds[writeIndex] = ReadString(trackDict, "id");
                trackTitles[writeIndex] = ReadString(trackDict, "title");
                trackArtists[writeIndex] = ReadString(trackDict, "artist");
                trackAlbums[writeIndex] = ReadString(trackDict, "album");
                trackAlbumIds[writeIndex] = ReadString(trackDict, "album_id");
                trackDurations[writeIndex] = ReadInt(trackDict, "duration");
                trackCount++;
            }

            TrimToTrackCount();
            return true;
        }

        int FindInsertIndex(int slotIndex)
        {
            for (int i = 0; i < trackCount; i++)
            {
                if (slotIndex < trackSlotIndices[i]) return i;
            }
            return trackCount;
        }

        void ShiftRightFrom(int insertIndex)
        {
            for (int i = trackCount; i > insertIndex; i--)
            {
                trackSlotIndices[i] = trackSlotIndices[i - 1];
                trackSlotIds[i] = trackSlotIds[i - 1];
                trackIds[i] = trackIds[i - 1];
                trackTitles[i] = trackTitles[i - 1];
                trackArtists[i] = trackArtists[i - 1];
                trackAlbums[i] = trackAlbums[i - 1];
                trackAlbumIds[i] = trackAlbumIds[i - 1];
                trackDurations[i] = trackDurations[i - 1];
            }
        }

        void TrimToTrackCount()
        {
            if (trackCount == trackSlotIndices.Length) return;

            trackSlotIndices = CopyInts(trackSlotIndices, trackCount);
            trackSlotIds = CopyStrings(trackSlotIds, trackCount);
            trackIds = CopyStrings(trackIds, trackCount);
            trackTitles = CopyStrings(trackTitles, trackCount);
            trackArtists = CopyStrings(trackArtists, trackCount);
            trackAlbums = CopyStrings(trackAlbums, trackCount);
            trackAlbumIds = CopyStrings(trackAlbumIds, trackCount);
            trackDurations = CopyInts(trackDurations, trackCount);
        }

        string[] CopyStrings(string[] source, int size)
        {
            string[] dst = new string[size];
            for (int i = 0; i < size; i++) dst[i] = source[i];
            return dst;
        }

        int[] CopyInts(int[] source, int size)
        {
            int[] dst = new int[size];
            for (int i = 0; i < size; i++) dst[i] = source[i];
            return dst;
        }

        int SlotIdToIndex(string slotId)
        {
            int slotNumber;
            if (!int.TryParse(slotId, out slotNumber)) return -1;
            return slotNumber - 1;
        }

        string ReadString(DataDictionary dict, string key)
        {
            DataToken token;
            if (!dict.TryGetValue(key, out token)) return string.Empty;
            if (token.TokenType == TokenType.String) return token.String;
            if (token.TokenType == TokenType.Null) return string.Empty;
            if (token.IsNumber) return token.Number.ToString();
            return token.ToString();
        }

        int ReadInt(DataDictionary dict, string key)
        {
            DataToken token;
            if (!dict.TryGetValue(key, out token)) return 0;
            if (token.IsNumber) return (int)token.Number;
            if (token.TokenType == TokenType.String)
            {
                int parsed;
                if (int.TryParse(token.String, out parsed)) return parsed;
            }
            return 0;
        }
    }
}
