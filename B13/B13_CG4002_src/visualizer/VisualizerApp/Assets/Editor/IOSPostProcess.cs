#if UNITY_IOS
using System.IO;
using UnityEditor;
using UnityEditor.Callbacks;
using UnityEditor.iOS.Xcode;

namespace CG4002.Visualizer.Editor
{
    public static class IOSPostProcess
    {
        [PostProcessBuild]
        public static void AddLocalNetworkPrivacy(BuildTarget target, string buildPath)
        {
            if (target != BuildTarget.iOS)
            {
                return;
            }

            string plistPath = Path.Combine(buildPath, "Info.plist");
            PlistDocument plist = new();
            plist.ReadFromFile(plistPath);

            PlistElementDict root = plist.root;
            root.SetString(
                "NSLocalNetworkUsageDescription",
                "Local network access connects this visualizer to the CG4002 laptop game server.");

            PlistElementDict transportSecurity;
            if (root.values.TryGetValue("NSAppTransportSecurity", out PlistElement existing))
            {
                transportSecurity = existing.AsDict();
            }
            else
            {
                transportSecurity = root.CreateDict("NSAppTransportSecurity");
            }

            transportSecurity.SetBoolean("NSAllowsLocalNetworking", true);
            plist.WriteToFile(plistPath);

            // Xcode 26 and newer support iOS 15+ deployment targets. Apply the
            // minimum to both generated Unity targets so it survives rebuilds.
            string projectPath = PBXProject.GetPBXProjectPath(buildPath);
            PBXProject project = new();
            project.ReadFromFile(projectPath);
            project.SetBuildProperty(
                project.GetUnityMainTargetGuid(),
                "IPHONEOS_DEPLOYMENT_TARGET",
                "15.0");
            project.SetBuildProperty(
                project.GetUnityFrameworkTargetGuid(),
                "IPHONEOS_DEPLOYMENT_TARGET",
                "15.0");
            project.WriteToFile(projectPath);
        }
    }
}
#endif
