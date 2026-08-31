// Capture the slime in PLAY MODE, driving the real controls.
//
// The edit-mode capture works, but it drives the solver by hand: step, photograph,
// step. That produces a body that squashes and rebounds, and nothing else — no
// input, no abilities, no form changes, because none of those run outside play.
//
// Play mode gets all of it for free. The controller reads input, the abilities
// fire, the renderer feature draws normally, and the movement is the game's own
// rather than a reconstruction of it. So this drives the same controls a player
// would — move, jump — and photographs the result.
//
//   FRAME OUTER, YAW INNER, still. A solver's state cannot be revisited, so each
//   captured moment is photographed from every angle before time advances.
//
// Run:
//   Unity -batchmode -runTests -testPlatform PlayMode \
//         -testFilter Astral.Tessera.PlayTests.TesseraSlimePlayCapture

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using NUnit.Framework;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace Astral.Tessera.PlayTests
{
    public class TesseraSlimePlayCapture
    {
        const int Yaws = 4;
        const int Frames = 14;
        const int Size = 256;
        const int SettleFrames = 40;
        const int FramesBetweenShots = 4;

        static string OutDir => Environment.GetEnvironmentVariable("TESSERA_OUT")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                            "Tessera/out/slime");

        static Type Find(string name) => AppDomain.CurrentDomain.GetAssemblies()
            .SelectMany(a => { try { return a.GetTypes(); } catch { return Type.EmptyTypes; } })
            .FirstOrDefault(t => t != null && t.Name == name);

        static Component FindByName(string typeName) => UnityEngine.Object
            .FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None)
            .FirstOrDefault(b => b != null && b.GetType().Name == typeName);

        static object Invoke(object target, string name, params object[] args)
        {
            var method = target.GetType().GetMethods()
                .Where(m => m.Name == name && m.GetParameters().Length >= args.Length)
                .OrderBy(m => m.GetParameters().Length).FirstOrDefault();
            if (method == null) return null;
            var parameters = method.GetParameters();
            var full = new object[parameters.Length];
            for (int i = 0; i < parameters.Length; i++)
                full[i] = i < args.Length ? args[i]
                    : (parameters[i].HasDefaultValue ? parameters[i].DefaultValue : null);
            return method.Invoke(target, full);
        }

        [UnityTest]
        public IEnumerator JumpAndLand()
        {
            // The demo factory builds scenes with EDITOR APIs, which throw in play
            // mode ("This cannot be used during play mode"). The scene it saves is
            // the same one, so play mode loads that rather than rebuilding it.
            var scenePath = Environment.GetEnvironmentVariable("TESSERA_SCENE")
                ?? "Assets/SlimeKernel/Demo/Slime Lab.unity";
            var parameters = new LoadSceneParameters(LoadSceneMode.Single);
            EditorSceneManager.LoadSceneInPlayMode(scenePath, parameters);
            yield return null;
            for (int i = 0; i < 20 && FindByName("SlimeSimulation") == null; i++) yield return null;
            Debug.Log($"[tessera] play mode scene loaded: {scenePath}");

            var simulation = FindByName("SlimeSimulation");
            var body = FindByName("SlimeBody");
            var controller = FindByName("SlimeController");
            Assert.IsNotNull(simulation, "no SlimeSimulation in the built scene");

            // In play mode the body spawns itself; only force one if it did not.
            for (int i = 0; i < 30 && ParticleCount(simulation) == 0; i++) yield return null;
            if (ParticleCount(simulation) == 0) EnsureBody(simulation);
            Assert.Greater(ParticleCount(simulation), 0, "body has no particles; nothing would render");
            Debug.Log($"[tessera] play mode body: {ParticleCount(simulation)} particles");

            for (int i = 0; i < SettleFrames; i++) yield return null;

            var camera = Camera.main ?? UnityEngine.Object
                .FindObjectsByType<Camera>(FindObjectsSortMode.None).FirstOrDefault();
            Assert.IsNotNull(camera, "no camera");
            var followType = Find("SlimeCameraFollow");
            if (followType != null && camera.GetComponent(followType) is Behaviour follow) follow.enabled = false;

            camera.orthographic = true;
            MakeCutout(camera);

            // A translucent body reads dark against nothing, and the QA check that
            // catches genuinely crushed renders is right to flag it. The fix is a
            // light, not a looser threshold: a key riding the camera plus a fill,
            // exactly as the Blender presets do it.
            var key = new GameObject("TesseraKey").AddComponent<Light>();
            key.type = LightType.Directional; key.intensity = 2.2f;
            key.color = new Color(1f, 0.98f, 0.94f);
            var fillLamp = new GameObject("TesseraFill").AddComponent<Light>();
            fillLamp.type = LightType.Directional; fillLamp.intensity = 1.1f;
            fillLamp.color = new Color(0.86f, 0.9f, 1f);
            var target = new RenderTexture(Size, Size, 24, RenderTextureFormat.ARGBFloat);
            var texture = new Texture2D(Size, Size, TextureFormat.RGBAFloat, false);
            var hidden = HideTheSet(simulation, body);

            // The real controls, as a player would use them: move off, then jump.
            if (controller != null)
            {
                Invoke(controller, "SetMove", Vector3.right);
                Invoke(controller, "Jump");
            }

            var views = new List<byte[]>();
            var meta = new List<(int yaw, int frame, float deg)>();
            try
            {
                for (int f = 0; f < Frames; f++)
                {
                    for (int i = 0; i < FramesBetweenShots; i++) yield return null;
                    if (f == Frames / 2 && controller != null) Invoke(controller, "Jump");   // a second hop
                    var (centre, radius) = MeasureBody(simulation);
                    camera.orthographicSize = Mathf.Max(radius * 1.8f, 0.6f);
                    for (int y = 0; y < Yaws; y++)
                    {
                        float degrees = y * (360f / Yaws);
                        Place(camera, centre, radius, degrees, 18f);
                        // Lights ride the camera so every direction is lit the same;
                        // a world-fixed key silhouettes half the sheet.
                        key.transform.rotation = Quaternion.Euler(35f, degrees - 35f, 0f);
                        fillLamp.transform.rotation = Quaternion.Euler(12f, degrees + 130f, 0f);
                        views.Add(Capture(camera, target, texture, "jump"));
                        meta.Add((y, f, degrees));
                    }
                }
                Directory.CreateDirectory(OutDir);
                var path = Path.Combine(OutDir, "slime-playmode-jump.tsf");
                WriteTsf(path, views, meta);
                Debug.Log($"[tessera] wrote {path} — {views.Count} views {Size}x{Size}");
                Assert.Greater(views.Count, 0);
            }
            finally
            {
                camera.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(texture);
                target.Release(); UnityEngine.Object.DestroyImmediate(target);
                foreach (var r in hidden) if (r != null) r.enabled = true;
                if (key != null) UnityEngine.Object.DestroyImmediate(key.gameObject);
                if (fillLamp != null) UnityEngine.Object.DestroyImmediate(fillLamp.gameObject);
            }
        }

        /// <summary>Every element, each with the same jump, so a sheet per ability.</summary>
        [UnityTest]
        public IEnumerator EveryElementJumping()
        {
            var scenePath = Environment.GetEnvironmentVariable("TESSERA_SCENE")
                ?? "Assets/SlimeKernel/Demo/Slime Lab.unity";
            EditorSceneManager.LoadSceneInPlayMode(scenePath, new LoadSceneParameters(LoadSceneMode.Single));
            yield return null;
            for (int i = 0; i < 20 && FindByName("SlimeSimulation") == null; i++) yield return null;

            var simulation = FindByName("SlimeSimulation");
            var body = FindByName("SlimeBody");
            var controller = FindByName("SlimeController");
            Assert.IsNotNull(simulation, "no SlimeSimulation");
            for (int i = 0; i < 40 && ParticleCount(simulation) == 0; i++) yield return null;
            if (ParticleCount(simulation) == 0) EnsureBody(simulation);
            Assert.Greater(ParticleCount(simulation), 0, "no particles");

            var profiles = ElementProfiles();
            Debug.Log($"[tessera] elements: {profiles.Count}");
            Assert.Greater(profiles.Count, 0, "no element profiles found");

            var camera = Camera.main ?? UnityEngine.Object
                .FindObjectsByType<Camera>(FindObjectsSortMode.None).FirstOrDefault();
            var followType = Find("SlimeCameraFollow");
            if (followType != null && camera.GetComponent(followType) is Behaviour f) f.enabled = false;
            camera.orthographic = true;
            MakeCutout(camera);

            var key = new GameObject("TesseraKey").AddComponent<Light>();
            key.type = LightType.Directional; key.intensity = 2.2f; key.color = new Color(1f, 0.98f, 0.94f);
            var fillLight = new GameObject("TesseraFill").AddComponent<Light>();
            fillLight.type = LightType.Directional; fillLight.intensity = 1.1f;
            fillLight.color = new Color(0.86f, 0.9f, 1f);

            var target = new RenderTexture(Size, Size, 24, RenderTextureFormat.ARGBFloat);
            var texture = new Texture2D(Size, Size, TextureFormat.RGBAFloat, false);
            var hidden = HideTheSet(simulation, body);
            Directory.CreateDirectory(OutDir);
            try
            {
                foreach (var profile in profiles)
                {
                    if (body != null) Invoke(body, "SetMakeup", profile, 0.05f);
                    for (int i = 0; i < 25; i++) yield return null;      // let the makeup take
                    if (controller != null) { Invoke(controller, "SetMove", Vector3.right); Invoke(controller, "Jump"); }

                    var views = new List<byte[]>();
                    var meta = new List<(int, int, float)>();

                    // Frame the shot ONCE, at rest, and hold it for every view.
                    // Re-measuring per frame re-centres and re-scales the body
                    // each time, which subtracts exactly the vertical travel the
                    // sheet exists to show: every sheet captured before this had
                    // an identical anchor and content box across all 14 time
                    // samples — a jump sheet with no jump in it. The wider size
                    // leaves headroom for the arc so the slime does not clip out
                    // of frame at the top.
                    var (restCentre, restRadius) = MeasureBody(simulation);
                    float shotSize = Mathf.Max(restRadius * 3.2f, 1.0f);
                    var shotCentre = restCentre + Vector3.up * restRadius * 1.1f;

                    for (int frame = 0; frame < Frames; frame++)
                    {
                        for (int i = 0; i < FramesBetweenShots; i++) yield return null;
                        if (frame == Frames / 2 && controller != null) Invoke(controller, "Jump");
                        var centre = shotCentre;
                        var radius = restRadius;
                        camera.orthographicSize = shotSize;
                        for (int y = 0; y < Yaws; y++)
                        {
                            float degrees = y * (360f / Yaws);
                            Place(camera, centre, radius, degrees, 18f);
                            key.transform.rotation = Quaternion.Euler(35f, degrees - 35f, 0f);
                            fillLight.transform.rotation = Quaternion.Euler(12f, degrees + 130f, 0f);
                            views.Add(Capture(camera, target, texture, profile.name));
                            meta.Add((y, frame, degrees));
                        }
                    }
                    string safe = new string(profile.name.Select(c => char.IsLetterOrDigit(c) ? c : '_').ToArray());
                    var path = Path.Combine(OutDir, $"slime-{safe}.tsf");
                    WriteTsf(path, views, meta);
                    Debug.Log($"[tessera] {profile.name}: {views.Count} views -> {path}");
                }
            }
            finally
            {
                camera.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(texture);
                target.Release(); UnityEngine.Object.DestroyImmediate(target);
                foreach (var r in hidden) if (r != null) r.enabled = true;
                UnityEngine.Object.DestroyImmediate(key.gameObject);
                UnityEngine.Object.DestroyImmediate(fillLight.gameObject);
            }
        }

        static List<UnityEngine.Object> ElementProfiles()
        {
            var found = new List<UnityEngine.Object>();
            var elementsType = Find("SlimeExperimentalElements");
            var enumType = Find("SlimeExperimentalElement");
            var displayName = elementsType?.GetMethod("DisplayName", BindingFlags.Public | BindingFlags.Static);
            var profileType = Find("SlimeProfile");
            if (enumType == null || displayName == null || profileType == null) return found;
            foreach (var value in Enum.GetValues(enumType))
            {
                string label = (string)displayName.Invoke(null, new[] { value });
                foreach (var guid in UnityEditor.AssetDatabase.FindAssets($"\"{label}\" t:{profileType.Name}"))
                {
                    var asset = UnityEditor.AssetDatabase.LoadAssetAtPath(
                        UnityEditor.AssetDatabase.GUIDToAssetPath(guid), profileType);
                    if (asset != null) { found.Add(asset); break; }
                }
            }
            return found;
        }

        /// <summary>Give the solver a body when the scene did not spawn one.
        /// A SlimeSimulation with no particles renders nothing, which reads as a
        /// broken capture rather than an empty one.</summary>
        static void EnsureBody(Component simulation)
        {
            var sampler = Find("SlimeMeshSampler");
            var fillSphere = sampler?.GetMethod("FillSphere", BindingFlags.Public | BindingFlags.Static);
            var working = simulation.GetType().GetProperty("Working")?.GetValue(simulation);
            float spacing = (float)(working?.GetType().GetProperty("Spacing")?.GetValue(working) ?? 0.08f);
            int capacity = (int)(simulation.GetType().GetProperty("Capacity")?.GetValue(simulation) ?? 1800);
            var points = fillSphere?.Invoke(null, new object[] {
                new Vector3(0f, 1.6f, 0f), 0.55f, spacing, capacity });
            Invoke(simulation, "AddParticles", points, 0, Vector3.zero, false);
            Debug.Log($"[tessera] body created: {ParticleCount(simulation)} particles");
        }


        /// <summary>Make the camera produce a CUT-OUT, not a screenshot.
        ///
        /// A clear colour with zero alpha is not enough on URP: post-processing
        /// writes opaque alpha, so the sheet comes back with a black background and
        /// every frame is a black box in an engine. The QA check caught this and I
        /// first read it as the check being wrong for a dark subject — it was not,
        /// the background really was opaque. Post-processing off, HDR off, and a
        /// render target that actually carries alpha.</summary>
        static void MakeCutout(Camera camera)
        {
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0f, 0f, 0f, 0f);
            camera.allowHDR = false;
            camera.allowMSAA = false;
            var data = camera.GetComponent("UniversalAdditionalCameraData");
            if (data != null)
            {
                var type = data.GetType();
                type.GetProperty("renderPostProcessing")?.SetValue(data, false);
                type.GetProperty("antialiasing")?.SetValue(data, 0);
                type.GetProperty("renderShadows")?.SetValue(data, true);
            }
        }

        static int ParticleCount(Component simulation) =>
            (int)(simulation.GetType().GetProperty("ParticleCount")?.GetValue(simulation) ?? 0);

        static List<Renderer> HideTheSet(Component simulation, Component body)
        {
            var keep = new HashSet<Renderer>();
            foreach (var component in new[] { simulation, body })
                if (component != null)
                    foreach (var r in component.GetComponentsInChildren<Renderer>(true)) keep.Add(r);
            var hidden = new List<Renderer>();
            foreach (var r in UnityEngine.Object.FindObjectsByType<Renderer>(FindObjectsSortMode.None))
            {
                if (keep.Contains(r) || !r.enabled) continue;
                r.enabled = false; hidden.Add(r);
            }
            Debug.Log($"[tessera] hid {hidden.Count} set renderers");
            return hidden;
        }

        static (Vector3, float) MeasureBody(Component simulation)
        {
            if (simulation.GetType().GetMethod("ReadPositions")?.Invoke(simulation, null) is Array positions
                && positions.Length > 0)
            {
                var lo = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue);
                var hi = new Vector3(float.MinValue, float.MinValue, float.MinValue);
                foreach (var item in positions)
                {
                    Vector3 p = item is Vector3 v ? v
                        : item is Vector4 v4 ? new Vector3(v4.x, v4.y, v4.z) : Vector3.zero;
                    lo = Vector3.Min(lo, p); hi = Vector3.Max(hi, p);
                }
                return ((lo + hi) * 0.5f, Mathf.Max((hi - lo).magnitude * 0.5f, 0.05f));
            }
            return (simulation.transform.position, 0.6f);
        }

        static void Place(Camera camera, Vector3 centre, float radius, float yawDeg, float elevationDeg)
        {
            float yaw = yawDeg * Mathf.Deg2Rad, elevation = elevationDeg * Mathf.Deg2Rad;
            var offset = new Vector3(
                Mathf.Sin(yaw) * Mathf.Cos(elevation), Mathf.Sin(elevation),
                -Mathf.Cos(yaw) * Mathf.Cos(elevation)) * Mathf.Max(radius * 9f, 4f);
            camera.transform.position = centre + offset;
            camera.transform.LookAt(centre);
        }

        static Color[] RenderOver(Camera camera, RenderTexture target, Texture2D texture, Color background)
        {
            var previous = RenderTexture.active;
            camera.backgroundColor = background;
            camera.targetTexture = target;
            camera.Render();
            RenderTexture.active = target;
            texture.ReadPixels(new Rect(0, 0, Size, Size), 0, 0);
            texture.Apply();
            camera.targetTexture = null;
            RenderTexture.active = previous;
            return texture.GetPixels();
        }

        /// <summary>Render twice and DERIVE the alpha. The camera cannot give it.
        ///
        /// The creator put the reason plainly: this camera renders everything for
        /// the GAME. It is a gameplay camera in a gameplay scene, not a capture rig,
        /// and a finished game frame is opaque by construction. Turning
        /// post-processing off and clearing to zero alpha changes what it clears TO,
        /// not whether the result is a finished frame.
        ///
        /// I removed this once on the strength of one in-run probe reporting 90%
        /// transparent pixels, and the very next packed sheet came back 96% opaque —
        /// corner pixel (0,0,0,255). The sheet is the artefact; the probe was
        /// measuring something else. Delivered output outranks an instrument reading
        /// taken mid-flight.
        ///
        /// The maths is exact for any renderer: over black a pixel reads c*a, over
        /// white c*a + (1-a). Their difference is (1-a) regardless of colour, so
        /// alpha falls out of the subtraction and un-multiplied colour follows.</summary>
        static byte[] Capture(Camera camera, RenderTexture target, Texture2D texture, string label)
        {
            var overBlack = (Color[])RenderOver(camera, target, texture,
                new Color(0f, 0f, 0f, 1f)).Clone();
            var overWhite = RenderOver(camera, target, texture, new Color(1f, 1f, 1f, 1f));

            var pixels = new Color[overBlack.Length];
            for (int i = 0; i < pixels.Length; i++)
            {
                var b = overBlack[i];
                var w = overWhite[i];
                float gap = Mathf.Clamp01(Mathf.Min(Mathf.Min(w.r - b.r, w.g - b.g), w.b - b.b));
                float alpha = Mathf.Clamp01(1f - gap);
                pixels[i] = alpha <= 0.004f
                    ? new Color(0f, 0f, 0f, 0f)
                    : new Color(b.r / alpha, b.g / alpha, b.b / alpha, alpha);
            }

            // Background differencing cannot matte an ADDITIVE subject. A material
            // that writes emission but no coverage — his EXP Glitch family sets
            // transmittance 1.0 and never assigns response.coverage — reads the
            // background back almost unchanged, so `gap` is ~1 and every derived
            // alpha collapses to zero. That is what turned a full 56-view capture
            // into a 56x16 sheet with not one inked pixel.
            //
            // Over BLACK such a subject reads exactly its own emission with no
            // background contaminating it, which is already a valid matte: take
            // luminance as coverage and un-premultiply the colour by it.
            //
            // This fires ONLY when differencing found essentially nothing, so the
            // six elements that matte correctly are untouched, and it says so out
            // loud — a fallback that engages in silence is the failure it is
            // meant to catch.
            int mattedByDifference = 0;
            for (int i = 0; i < pixels.Length; i++)
                if (pixels[i].a > 0.004f) mattedByDifference++;

            if (mattedByDifference * 200 < pixels.Length)   // under 0.5% of the frame
            {
                int mattedByLuminance = 0;
                for (int i = 0; i < pixels.Length; i++)
                {
                    var b = overBlack[i];
                    float luma = 0.2126f * b.r + 0.7152f * b.g + 0.0722f * b.b;
                    if (luma <= 0.004f) { pixels[i] = new Color(0f, 0f, 0f, 0f); continue; }
                    // Alpha is coverage and belongs in [0,1]; COLOUR is energy and
                    // does not. Clamping it here is what turns a glow into a flat
                    // matte, so the over-range travels in the float .tsf and the
                    // packer normalises it into the sheet with a recorded scale.
                    float alpha = Mathf.Clamp01(luma);
                    pixels[i] = new Color(b.r / alpha, b.g / alpha, b.b / alpha, alpha);
                    mattedByLuminance++;
                }

                if (mattedByLuminance * 200 >= pixels.Length)
                    Debug.Log($"[tessera] {label}: additive matte — differencing found "
                              + $"{mattedByDifference} px, luminance recovered {mattedByLuminance}");
                else
                    Debug.LogWarning($"[tessera] {label}: NOTHING to matte — differencing "
                                     + $"{mattedByDifference} px, luminance {mattedByLuminance}. "
                                     + "This frame is genuinely empty.");
            }
            var bytes = new byte[Size * Size * 16];
            int at = 0;
            for (int y = Size - 1; y >= 0; y--)      // Unity is bottom-up; TSF is top-down
            {
                int row = y * Size;
                for (int x = 0; x < Size; x++)
                {
                    var c = pixels[row + x];
                    foreach (float ch in new[] { c.r, c.g, c.b, c.a })
                    { Buffer.BlockCopy(BitConverter.GetBytes(ch), 0, bytes, at, 4); at += 4; }
                }
            }
            return bytes;
        }

        static void WriteTsf(string path, List<byte[]> views, List<(int yaw, int frame, float deg)> meta)
        {
            using var stream = new FileStream(path, FileMode.Create, FileAccess.Write);
            using var writer = new BinaryWriter(stream);
            writer.Write(new[] { (byte)'T', (byte)'S', (byte)'F', (byte)'1' });
            writer.Write(Size); writer.Write(Size); writer.Write(views.Count);
            for (int i = 0; i < views.Count; i++)
            {
                writer.Write(meta[i].yaw); writer.Write(meta[i].frame);
                writer.Write(meta[i].deg); writer.Write(meta[i].frame);
                writer.Write(views[i]);
            }
        }
    }
}
