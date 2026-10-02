<#
Zoo desktop agent. Runs in the zoo user's desktop session (scheduled task at logon) so window and app tools
see and start real windows; commands run over SSH land in a background session without a desktop.

Listens on 127.0.0.1:7071 only. The API reaches it through its SSH connection to the guest. Each connection
sends one line, a base64 UTF-8 PowerShell script, and gets back one line: "ok <base64 output>" or
"err <base64 message>".
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class ZooWin {
    delegate bool EnumProc(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc proc, IntPtr param);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int max);
    [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr hwnd, uint cmd);
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr hwnd, int index);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out int value, int size);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);

    public class Window { public string id; public string title; public string app; public int pid; }

    public static List<Window> List() {
        var found = new List<Window>();
        EnumWindows((hwnd, _) => {
            if (!IsWindowVisible(hwnd) || GetWindow(hwnd, 4) != IntPtr.Zero) return true;  // GW_OWNER
            if ((GetWindowLong(hwnd, -20) & 0x80) != 0) return true;  // WS_EX_TOOLWINDOW
            int cloaked;
            if (DwmGetWindowAttribute(hwnd, 14, out cloaked, 4) == 0 && cloaked != 0) return true;  // DWMWA_CLOAKED
            int length = GetWindowTextLength(hwnd);
            if (length == 0) return true;
            var text = new StringBuilder(length + 1);
            GetWindowText(hwnd, text, text.Capacity);
            uint pid;
            GetWindowThreadProcessId(hwnd, out pid);
            string app = "";
            try { app = Process.GetProcessById((int)pid).ProcessName; } catch {}
            found.Add(new Window { id = hwnd.ToInt64().ToString(), title = text.ToString(), app = app, pid = (int)pid });
            return true;
        }, IntPtr.Zero);
        return found;
    }

    static IntPtr Handle(string id) {
        var hwnd = new IntPtr(long.Parse(id));
        if (!IsWindow(hwnd)) throw new ArgumentException("no window " + id + " (use an id from windows_list)");
        return hwnd;
    }

    public static void Show(string id, int cmd) { ShowWindow(Handle(id), cmd); }

    public static void Focus(string id) {
        var hwnd = Handle(id);
        ShowWindow(hwnd, 9);  // SW_RESTORE
        // Windows only lets the process that last had input change the foreground; a synthetic Alt counts.
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        keybd_event(0x12, 0, 2, UIntPtr.Zero);
        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
    }

    public static void Close(string id) { PostMessage(Handle(id), 0x10, IntPtr.Zero, IntPtr.Zero); }  // WM_CLOSE

    public static bool HasWindow(int pid) {
        foreach (var w in List()) if (w.pid == pid) return true;
        return false;
    }
}
'@

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 7071)
$listener.Start()
while ($true) {
    $client = $listener.AcceptTcpClient()
    try {
        $stream = $client.GetStream()
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::ASCII)
        $writer = [IO.StreamWriter]::new($stream, [Text.Encoding]::ASCII)
        $script = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($reader.ReadLine()))
        try {
            $output = & ([ScriptBlock]::Create($script)) | Out-String
            $reply = 'ok ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($output))
        } catch {
            $reply = 'err ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_.Exception.Message))
        }
        $writer.WriteLine($reply)
        $writer.Flush()
    } catch {
    } finally {
        $client.Close()
    }
}
