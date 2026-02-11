using JLChnToZ.VRC.VVMW;
using UdonSharp;
using UnityEngine;
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

        [Header("Runtime State (do not edit)")]
        [HideInInspector] public string[] trackTitles;
        [HideInInspector] public string[] trackArtists;
        [HideInInspector] public int[] trackDurations;
        [HideInInspector] public int[] trackSlotIndices;
        [HideInInspector] public int trackCount;

        void Start()
        {
            VRCStringDownloader.LoadUrl(metadataUrl, (IUdonEventReceiver)this);
        }

        public override void OnStringLoadSuccess(IVRCStringDownload result)
        {
            // TODO: Parse result.Result JSON, populate track arrays
            Debug.Log("[SubsonicBrowser] Metadata loaded successfully.");
        }

        public override void OnStringLoadError(IVRCStringDownload result)
        {
            Debug.LogError($"[SubsonicBrowser] Failed to load metadata: {result.Error} (code {result.ErrorCode})");
        }

        public void PlayTrack(int trackIndex)
        {
            if (trackIndex < 0 || trackIndex >= trackCount) return;
            int slotIndex = trackSlotIndices[trackIndex];
            VRCUrl url = slotUrls[slotIndex];
            string title = trackTitles[trackIndex];
            frontendHandler.PlayUrl(url, url, title, playerIndex);
        }
    }
}
