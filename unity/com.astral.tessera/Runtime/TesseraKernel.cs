// Binding to the compiled Tessera kernel.
//
// Unity gets the SAME binary the Flutter client and the Blender adapter call.
// That is the point of shipping a kernel rather than a source library: ASCII needs
// a divergence GATE because three hosts each reimplement its contract, and a host
// that links one binary cannot diverge because there is nothing to diverge from.
//
// Every pointer returned here is owned by the caller until passed to its Free.
// The managed wrapper below copies out before freeing, so callers never hold a
// pointer into native memory.

using System;
using System.Runtime.InteropServices;

namespace Astral.Tessera
{
    public sealed class TesseraKernel : IDisposable
    {
#if UNITY_IOS && !UNITY_EDITOR
        private const string Lib = "__Internal";
#else
        private const string Lib = "tessera_core";
#endif

        [DllImport(Lib)] private static extern IntPtr tessera_version();
        [DllImport(Lib)] private static extern IntPtr tessera_last_error();
        [DllImport(Lib)] private static extern IntPtr tessera_kernel_open(string path);
        [DllImport(Lib)] private static extern void tessera_kernel_free(IntPtr handle);
        [DllImport(Lib)] private static extern UIntPtr tessera_kernel_fingerprint(
            IntPtr handle, byte[] buffer, UIntPtr capacity);
        [DllImport(Lib)] private static extern IntPtr tessera_sheet_from_frames(
            IntPtr handle, string framesPath, string optionsJson);
        [DllImport(Lib)] private static extern IntPtr tessera_result_png(
            IntPtr result, out UIntPtr length);
        [DllImport(Lib)] private static extern IntPtr tessera_result_meta(IntPtr result);
        [DllImport(Lib)] private static extern bool tessera_result_passed(IntPtr result);
        [DllImport(Lib)] private static extern void tessera_result_free(IntPtr result);

        private IntPtr _handle;

        public static string Version => Marshal.PtrToStringAnsi(tessera_version());

        private static string LastError()
        {
            IntPtr ptr = tessera_last_error();
            return ptr == IntPtr.Zero ? "unknown" : Marshal.PtrToStringAnsi(ptr);
        }

        public TesseraKernel(string kernelJsonPath)
        {
            _handle = tessera_kernel_open(kernelJsonPath);
            if (_handle == IntPtr.Zero)
                throw new InvalidOperationException("tessera_kernel_open failed: " + LastError());
        }

        public string Fingerprint
        {
            get
            {
                var buffer = new byte[80];
                tessera_kernel_fingerprint(_handle, buffer, (UIntPtr)buffer.Length);
                int end = Array.IndexOf(buffer, (byte)0);
                return System.Text.Encoding.ASCII.GetString(buffer, 0, end < 0 ? buffer.Length : end);
            }
        }

        public sealed class Sheet
        {
            public byte[] Png;
            public string MetaJson;
            public bool Passed;
        }

        /// <summary>Build a sheet from a captured .tsf. Options are the C ABI's JSON.</summary>
        public Sheet SheetFromFrames(string framesPath, string optionsJson)
        {
            IntPtr result = tessera_sheet_from_frames(_handle, framesPath, optionsJson);
            if (result == IntPtr.Zero)
                throw new InvalidOperationException("sheet build failed: " + LastError());
            try
            {
                IntPtr bytes = tessera_result_png(result, out UIntPtr length);
                var png = new byte[(int)length];
                Marshal.Copy(bytes, png, 0, png.Length);   // copy before free
                return new Sheet
                {
                    Png = png,
                    MetaJson = Marshal.PtrToStringAnsi(tessera_result_meta(result)),
                    Passed = tessera_result_passed(result),
                };
            }
            finally { tessera_result_free(result); }
        }

        public void Dispose()
        {
            if (_handle != IntPtr.Zero) { tessera_kernel_free(_handle); _handle = IntPtr.Zero; }
        }
    }
}
