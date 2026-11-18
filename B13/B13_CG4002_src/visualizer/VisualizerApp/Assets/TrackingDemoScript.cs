using UnityEngine;
using UnityEngine.XR.ARFoundation;

public class TrackingDemoScript : MonoBehaviour
{
    [SerializeField]
    private Camera arCamera;

    private GameObject cube;

    private void OnEnable()
    {
        ARSession.stateChanged += OnSessionStateChanged;
    }

    private void OnDisable()
    {
        ARSession.stateChanged -= OnSessionStateChanged;
    }

    private void OnSessionStateChanged(
        ARSessionStateChangedEventArgs eventArgs)
    {
        Debug.Log($"AR state: {eventArgs.state}");

        if (eventArgs.state == ARSessionState.SessionTracking &&
            cube == null)
        {
            CreateCube();
        }

        if (eventArgs.state == ARSessionState.SessionInitializing)
        {
            Debug.Log(
                $"Not tracking because: {ARSession.notTrackingReason}");
        }
    }

    private void CreateCube()
    {
        cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
        cube.name = "Tracking Test Cube";

        cube.transform.position =
            arCamera.transform.position +
            arCamera.transform.forward * 1.0f;

        cube.transform.localScale =
            Vector3.one * 0.1f;
    }
}