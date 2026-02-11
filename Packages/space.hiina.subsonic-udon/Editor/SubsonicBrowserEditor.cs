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

            if (GUILayout.Button("Generate Slots"))
            {
                GenerateSlots();
            }
        }

        void GenerateSlots()
        {
            var so = serializedObject;

            // Set metadataUrl
            var metadataProp = so.FindProperty("metadataUrl");
            SetVRCUrl(metadataProp, $"{baseUrl}/metadata.json");

            // Set slotUrls array
            var slotsProp = so.FindProperty("slotUrls");
            slotsProp.arraySize = slotCount;
            for (int i = 0; i < slotCount; i++)
            {
                string url = $"{baseUrl}/{(i + 1):D4}.m3u8";
                SetVRCUrl(slotsProp.GetArrayElementAtIndex(i), url);
            }

            so.ApplyModifiedProperties();
            Debug.Log($"[SubsonicBrowser] Generated {slotCount} slot URLs with base {baseUrl}");
        }

        static void SetVRCUrl(SerializedProperty prop, string url)
        {
            // VRCUrl stores the URL string in a nested field called "url"
            var urlField = prop.FindPropertyRelative("url");
            if (urlField != null)
                urlField.stringValue = url;
        }
    }
}
