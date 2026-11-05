using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace BaseerLocal {
    public static class CredentialStore {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct Credential {
            public uint Flags, Type;
            public string TargetName, Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public uint CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint Persist, AttributeCount;
            public IntPtr Attributes;
            public string TargetAlias, UserName;
        }
        [DllImport("advapi32.dll", EntryPoint="CredWriteW", CharSet=CharSet.Unicode, SetLastError=true)]
        private static extern bool CredWrite(ref Credential credential, uint flags);
        [DllImport("advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, SetLastError=true)]
        private static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);
        [DllImport("advapi32.dll", EntryPoint="CredDeleteW", CharSet=CharSet.Unicode, SetLastError=true)]
        private static extern bool CredDelete(string target, uint type, uint flags);
        [DllImport("advapi32.dll")]
        private static extern void CredFree(IntPtr buffer);

        private static void Clear(IntPtr pointer, int length) {
            for (int i = 0; i < length; i++) Marshal.WriteByte(pointer, i, 0);
        }
        private static void FreeCredential(IntPtr pointer) {
            if (pointer == IntPtr.Zero) return;
            try {
                var value = (Credential)Marshal.PtrToStructure(pointer, typeof(Credential));
                if (value.CredentialBlob != IntPtr.Zero) Clear(value.CredentialBlob, checked((int)value.CredentialBlobSize));
            } finally { CredFree(pointer); }
        }
        public static bool Exists(string target) {
            IntPtr pointer;
            if (!CredRead(target, 1, 0, out pointer)) {
                if (Marshal.GetLastWin32Error() == 1168) return false;
                throw new InvalidOperationException("Windows Credential Manager is unavailable.");
            }
            FreeCredential(pointer);
            return true;
        }
        public static void Save(string target, byte[] value) {
            if (value == null || value.Length == 0 || value.Length > 2560) throw new ArgumentException("Invalid credential size.");
            var pointer = Marshal.AllocHGlobal(value.Length);
            try {
                Marshal.Copy(value, 0, pointer, value.Length);
                var credential = new Credential {
                    Type = 1, TargetName = target, Comment = "Baseer local Odoo API connection",
                    CredentialBlobSize = (uint)value.Length, CredentialBlob = pointer,
                    Persist = 2, UserName = "Baseer Odoo API"
                };
                if (!CredWrite(ref credential, 0)) throw new InvalidOperationException("Windows Credential Manager could not save the connection.");
            } finally { Clear(pointer, value.Length); Marshal.FreeHGlobal(pointer); }
        }
        public static byte[] Read(string target) {
            IntPtr pointer;
            if (!CredRead(target, 1, 0, out pointer)) throw new InvalidOperationException("Connection is missing or Windows Credential Manager refused access.");
            try {
                var credential = (Credential)Marshal.PtrToStructure(pointer, typeof(Credential));
                if (credential.CredentialBlobSize > 2560) throw new InvalidOperationException("Invalid stored connection.");
                var value = new byte[credential.CredentialBlobSize];
                Marshal.Copy(credential.CredentialBlob, value, 0, value.Length);
                return value;
            } finally { FreeCredential(pointer); }
        }
        public static void DeleteTest(string target) {
            if (!target.StartsWith("BaseerCodex/TEST/", StringComparison.Ordinal)) throw new InvalidOperationException("Only test entries can be deleted by this helper.");
            if (!CredDelete(target, 1, 0) && Marshal.GetLastWin32Error() != 1168) throw new InvalidOperationException("Could not remove test entry.");
        }
    }
}
