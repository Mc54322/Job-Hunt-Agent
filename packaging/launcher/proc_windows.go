//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"time"
)

const isWindows = true

// Ctrl+C arrives as os.Interrupt; closing the console window as SIGTERM.
var stopSignals = []os.Signal{os.Interrupt, syscall.SIGTERM}

func uvInstallCommand() *exec.Cmd {
	return exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "ByPass", "-Command",
		"irm https://astral.sh/uv/install.ps1 | iex")
}

// Windows services share the console, so no process group is needed; each one and its
// children are stopped by process tree (taskkill /T).
func setProcessGroup(cmd *exec.Cmd) {}

func stopProcess(cmd *exec.Cmd) {
	if cmd.Process != nil {
		_ = exec.Command("taskkill", "/PID", fmt.Sprint(cmd.Process.Pid), "/T").Run()
	}
}

func killProcess(cmd *exec.Cmd) {
	if cmd.Process != nil {
		_ = exec.Command("taskkill", "/PID", fmt.Sprint(cmd.Process.Pid), "/T", "/F").Run()
	}
}

// clearLeftovers stops JobAssist services left behind by a copy that didn't shut down.
// The pattern is split in two so this PowerShell command never matches itself.
func clearLeftovers() {
	script := "$p = 'jobassist.' + 'Microservices'; " +
		"Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like ('*' + $p + '*') } | " +
		"ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
	_ = exec.Command("powershell", "-NoProfile", "-Command", script).Run()
	time.Sleep(2 * time.Second)
}

func openBrowser(url string) {
	_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
}
