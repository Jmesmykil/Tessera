// Writing the TSF frame bridge from Unity.
//
// Format is shared with the Blender adapter and the Rust reader, and TOP-DOWN is
// stated in all three because Unity's ReadPixels is bottom-up like Blender's. A
// silently flipped sheet passes review: every frame looks plausible on its own,
// and only a shadow on the wrong side gives it away.

using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Astral.Tessera
{
    public struct TesseraView
    {
        public int YawIndex;
        public int FrameIndex;
        public float YawDegrees;
        public int FrameNumber;
        public float[] Rgba;      // top-down, row-major, 0..1
    }

    public static class TesseraFrameWriter
    {
        public static void Write(string path, int width, int height, IList<TesseraView> views)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            using var stream = new FileStream(path, FileMode.Create, FileAccess.Write);
            using var writer = new BinaryWriter(stream);
            writer.Write(new[] { (byte)'T', (byte)'S', (byte)'F', (byte)'1' });
            writer.Write(width);
            writer.Write(height);
            writer.Write(views.Count);
            int expected = width * height * 4;
            foreach (var view in views)
            {
                if (view.Rgba.Length != expected)
                    throw new IOException($"view {view.YawIndex}/{view.FrameIndex} has "
                                          + $"{view.Rgba.Length} values, expected {expected}");
                writer.Write(view.YawIndex);
                writer.Write(view.FrameIndex);
                writer.Write(view.YawDegrees);
                writer.Write(view.FrameNumber);
                foreach (float value in view.Rgba) writer.Write(value);
            }
        }

        /// <summary>Read a camera's target into top-down RGBA. Unity is bottom-up.</summary>
        public static float[] ReadCamera(Camera camera, int size)
        {
            var target = new RenderTexture(size, size, 24, RenderTextureFormat.ARGBFloat)
            {
                antiAliasing = 1
            };
            var previousTarget = camera.targetTexture;
            var previousActive = RenderTexture.active;
            var texture = new Texture2D(size, size, TextureFormat.RGBAFloat, false);
            try
            {
                camera.targetTexture = target;
                camera.Render();
                RenderTexture.active = target;
                texture.ReadPixels(new Rect(0, 0, size, size), 0, 0);
                texture.Apply();
                var pixels = texture.GetPixels();          // bottom-up
                var flat = new float[size * size * 4];
                for (int y = 0; y < size; y++)
                {
                    int source = (size - 1 - y) * size;     // flip to top-down
                    for (int x = 0; x < size; x++)
                    {
                        var c = pixels[source + x];
                        int o = (y * size + x) * 4;
                        flat[o] = c.r; flat[o + 1] = c.g; flat[o + 2] = c.b; flat[o + 3] = c.a;
                    }
                }
                return flat;
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                Object.DestroyImmediate(texture);
                target.Release();
                Object.DestroyImmediate(target);
            }
        }
    }
}
