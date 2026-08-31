// Capture the slime, headless: jump, land, bounce — per element.
//
// Four earlier attempts photographed an empty room, and the cause was not URP:
// THE SIMULATION HAD NO PARTICLES. Opening a saved scene gives you a
// SlimeSimulation component, not a slime. The kernel's own validation harness
// shows what a live body needs, and this follows it exactly:
//
//   ConfigurePipeline()      registers the renderer feature that draws the body
//   synchronousReadbacks     without it the CPU never learns where the body is
//   Initialise()             allocates the buffers
//   AddParticles(FillSphere) puts a body in the world — nothing draws without this
//
// One rule is Tessera's own and is not negotiable:
//
//   FRAME OUTER, YAW INNER.
//
// A rigged character can be sampled at any frame in any order, because a pose is a
// pure function of time. A solver cannot: step once, photograph that state from
// every angle, then step again. Doing it the other way photographs several
// different simulations and presents them as several views of one, which looks
// almost right — the dangerous kind of wrong.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace Astral.Tessera.Editor
{
    public static class TesseraSlimeCapture
    {
        static string Arg(string name, string fallback)
        {
            var args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return fallback;
        }

        static Type Find(string name) => AppDomain.CurrentDomain.GetAssemblies()
            .SelectMany(a => { try { return a.GetTypes(); } catch { return Type.EmptyTypes; } })
            .FirstOrDefault(t => t != null && t.Name == name);

        static void Fail(string message)
        {
            Debug.LogError("[tessera] " + message);
            EditorApplication.Exit(2);
        }

        public static void Run()
        {
            string outDir = Arg("-tesseraOutDir", Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Tessera/out/slime"));
            string wanted = Arg("-tesseraElement", "all");
            int yaws = int.Parse(Arg("-tesseraYaws", "4"));
            int frames = int.Parse(Arg("-tesseraFrames", "10"));
            int size = int.Parse(Arg("-tesseraSize", "256"));
            int settle = int.Parse(Arg("-tesseraSettle", "50"));
            int stepsPerFrame = int.Parse(Arg("-tesseraStepsPerFrame", "4"));
            float dt = 1f / 60f;

            var factory = Find("SlimeDemoSceneFactory");
            if (factory == null) { Fail("SlimeDemoSceneFactory not found"); return; }

            // Build the scene the way the kernel's own harness does. A hand-opened
            // scene has the components but not the pipeline that draws the body.
            object pipeline = factory.GetMethod("ConfigurePipeline", BindingFlags.Public | BindingFlags.Static)
                ?.Invoke(null, null);
            factory.GetMethod("GenerateShowcaseMaterials", BindingFlags.Public | BindingFlags.Static)?.Invoke(null, null);
            factory.GetMethod("GenerateExperimentalElementAssets", BindingFlags.Public | BindingFlags.Static)?.Invoke(null, null);
            factory.GetMethod("BuildScene", BindingFlags.Public | BindingFlags.Static)
                ?.Invoke(null, new object[] { pipeline, true });
            Debug.Log("[tessera] scene built through the kernel's own factory");

            var simulation = FindByName("SlimeSimulation");
            var body = FindByName("SlimeBody");
            var controller = FindByName("SlimeController");
            if (simulation == null) { Fail("no SlimeSimulation after building the scene"); return; }
            var simType = simulation.GetType();

            simType.GetField("synchronousReadbacks")?.SetValue(simulation, true);
            simType.GetField("spawnSphereOnAwake")?.SetValue(simulation, false);
            simType.GetMethod("Initialise")?.Invoke(simulation, null);

            var elements = ElementProfiles(wanted);
            Debug.Log($"[tessera] elements to capture: {string.Join(", ", elements.Select(e => e.name))}");
            if (elements.Count == 0) { Fail("no element profiles found — were the assets generated?"); return; }

            var camera = Camera.main ?? UnityEngine.Object
                .FindObjectsByType<Camera>(FindObjectsSortMode.None).FirstOrDefault();
            if (camera == null) { Fail("no camera in the built scene"); return; }
            var followType = Find("SlimeCameraFollow");
            if (followType != null && camera.GetComponent(followType) is Behaviour follow) follow.enabled = false;

            Directory.CreateDirectory(outDir);
            foreach (var element in elements)
            {
                CaptureElement(simulation, body, controller, camera, element,
                               Path.Combine(outDir, $"slime-{Safe(element.name)}.tsf"),
                               yaws, frames, size, settle, stepsPerFrame, dt);
            }
            EditorApplication.Exit(0);
        }

        static string Safe(string text) =>
            new string(text.Select(c => char.IsLetterOrDigit(c) ? c : '_').ToArray());

        /// <summary>Invoke by name, filling in any defaults reflection will not.</summary>
        static object Invoke(object target, string name, params object[] args)
        {
            var method = target.GetType().GetMethods()
                .Where(m => m.Name == name && m.GetParameters().Length >= args.Length)
                .OrderBy(m => m.GetParameters().Length)
                .FirstOrDefault();
            if (method == null) { Debug.LogError($"[tessera] no method {name}"); return null; }
            var parameters = method.GetParameters();
            var full = new object[parameters.Length];
            for (int i = 0; i < parameters.Length; i++)
                full[i] = i < args.Length ? args[i]
                    : (parameters[i].HasDefaultValue ? parameters[i].DefaultValue : null);
            return method.Invoke(target, full);
        }

        static Component FindByName(string typeName)
        {
            foreach (var behaviour in UnityEngine.Object
                         .FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None))
                if (behaviour != null && behaviour.GetType().Name == typeName) return behaviour;
            return null;
        }

        static List<UnityEngine.Object> ElementProfiles(string wanted)
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
                if (wanted != "all" && !label.ToLower().Contains(wanted.ToLower())) continue;
                // The generator writes one profile asset per element; find it by name
                // rather than guessing a path, so a moved folder does not break this.
                foreach (var guid in AssetDatabase.FindAssets($"\"{label}\" t:{profileType.Name}"))
                {
                    var asset = AssetDatabase.LoadAssetAtPath(
                        AssetDatabase.GUIDToAssetPath(guid), profileType);
                    if (asset != null) { found.Add(asset); break; }
                }
            }
            return found;
        }

        static void CaptureElement(Component simulation, Component body, Component controller,
                                   Camera camera, UnityEngine.Object profile, string outPath,
                                   int yaws, int frames, int size, int settle,
                                   int stepsPerFrame, float dt)
        {
            var simType = simulation.GetType();
            var stepper = simType.GetMethod("Step", new[] { typeof(float) });

            // A fresh body per element, so one element's deformation never carries
            // into the next and gets attributed to it.
            simType.GetMethod("Clear")?.Invoke(simulation, null);
            var sampler = Find("SlimeMeshSampler");
            var fill = sampler?.GetMethod("FillSphere", BindingFlags.Public | BindingFlags.Static);
            var working = simType.GetProperty("Working")?.GetValue(simulation);
            float spacing = (float)(working?.GetType().GetProperty("Spacing")?.GetValue(working) ?? 0.08f);
            int capacity = (int)(simType.GetProperty("Capacity")?.GetValue(simulation) ?? 1800);
            var points = fill?.Invoke(null, new object[] { new Vector3(0f, 1.6f, 0f), 0.55f, spacing, capacity });
            // Reflection does not apply C# default arguments: AddParticles takes
            // four parameters even though the last one has a default, and passing
            // three throws TargetParameterCountException rather than binding.
            Invoke(simulation, "AddParticles", points, 0, Vector3.zero, false);

            if (body != null)
            {
                var dress = body.GetType().GetMethod("Dress");
                var setMakeup = body.GetType().GetMethod("SetMakeup");
                if (dress != null) dress.Invoke(body, new object[] { profile });
                else setMakeup?.Invoke(body, new object[] { profile, 0.01f });
            }

            int particles = (int)(simType.GetProperty("ParticleCount")?.GetValue(simulation) ?? 0);
            if (particles == 0) { Debug.LogError($"[tessera] {profile.name}: no particles"); return; }

            for (int i = 0; i < settle; i++) stepper.Invoke(simulation, new object[] { dt });

            // Jump on the first captured frame, so the sheet is the arc: launch,
            // apex, fall, land, squash, settle — which is what a sprite of a jump has
            // to contain.
            controller?.GetType().GetMethod("Jump")?.Invoke(controller, null);

            camera.orthographic = true;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0, 0, 0, 0);
            var target = new RenderTexture(size, size, 24, RenderTextureFormat.ARGBFloat);
            var texture = new Texture2D(size, size, TextureFormat.RGBAFloat, false);
            var hidden = HideTheSet(simulation, body);

            var views = new List<byte[]>();
            var meta = new List<(int yaw, int frame, float deg)>();
            try
            {
                for (int f = 0; f < frames; f++)
                {
                    for (int s = 0; s < stepsPerFrame; s++) stepper.Invoke(simulation, new object[] { dt });
                    var (centre, radius) = MeasureBody(simulation);
                    camera.orthographicSize = Mathf.Max(radius * 1.8f, 0.6f);
                    for (int y = 0; y < yaws; y++)
                    {
                        float degrees = y * (360f / yaws);
                        Place(camera, centre, radius, degrees, 18f);
                        views.Add(Capture(camera, target, texture, size));
                        meta.Add((y, f, degrees));
                    }
                }
                WriteTsf(outPath, size, views, meta);
                Debug.Log($"[tessera] {profile.name}: {particles} particles, {views.Count} views -> {outPath}");
            }
            finally
            {
                camera.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(texture);
                target.Release(); UnityEngine.Object.DestroyImmediate(target);
                foreach (var r in hidden) if (r != null) r.enabled = true;
            }
        }

        /// <summary>Switch the level off. A sprite is of a subject, not of a room.</summary>
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
            Debug.Log($"[tessera] hid {hidden.Count} set renderers, kept {keep.Count} on the subject");
            return hidden;
        }

        /// <summary>Where the body is and how big, read from the particles themselves.</summary>
        static (Vector3 centre, float radius) MeasureBody(Component simulation)
        {
            var read = simulation.GetType().GetMethod("ReadPositions");
            if (read?.Invoke(simulation, null) is Array positions && positions.Length > 0)
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
                Mathf.Sin(yaw) * Mathf.Cos(elevation),
                Mathf.Sin(elevation),
                -Mathf.Cos(yaw) * Mathf.Cos(elevation)) * Mathf.Max(radius * 9f, 4f);
            camera.transform.position = centre + offset;
            camera.transform.LookAt(centre);
        }

        static byte[] Capture(Camera camera, RenderTexture target, Texture2D texture, int size)
        {
            var previous = RenderTexture.active;
            camera.targetTexture = target;
            camera.Render();
            RenderTexture.active = target;
            texture.ReadPixels(new Rect(0, 0, size, size), 0, 0);
            texture.Apply();
            camera.targetTexture = null;
            RenderTexture.active = previous;

            // Unity reads bottom-up; TSF is top-down and says so.
            var pixels = texture.GetPixels();
            var bytes = new byte[size * size * 16];
            int at = 0;
            for (int y = size - 1; y >= 0; y--)
            {
                int row = y * size;
                for (int x = 0; x < size; x++)
                {
                    var c = pixels[row + x];
                    foreach (float channel in new[] { c.r, c.g, c.b, c.a })
                    { Buffer.BlockCopy(BitConverter.GetBytes(channel), 0, bytes, at, 4); at += 4; }
                }
            }
            return bytes;
        }

        static void WriteTsf(string path, int size, List<byte[]> views,
                             List<(int yaw, int frame, float deg)> meta)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            using var stream = new FileStream(path, FileMode.Create, FileAccess.Write);
            using var writer = new BinaryWriter(stream);
            writer.Write(new[] { (byte)'T', (byte)'S', (byte)'F', (byte)'1' });
            writer.Write(size); writer.Write(size); writer.Write(views.Count);
            for (int i = 0; i < views.Count; i++)
            {
                writer.Write(meta[i].yaw); writer.Write(meta[i].frame);
                writer.Write(meta[i].deg); writer.Write(meta[i].frame);
                writer.Write(views[i]);
            }
        }
    }
}
