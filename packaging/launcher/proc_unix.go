//go:build !windows

package main

import (
	"os"
	"os/exec"
	"syscall"
	"time"
)

const isWindows = false

// Closing the Terminal window sends SIGHUP.
var stopSignals = []os.Signal{os.Interrupt, syscall.SIGTERM, syscall.SIGHUP}

func uvInstallCommand() *exec.Cmd {
	return exec.Command("sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh")
}

// setProcessGroup puts each service in its own process group, so stopping it also stops
// the Python server that 'uv run' started — and nothing belonging to anyone else.
func setProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

func stopProcess(cmd *exec.Cmd) {
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
	}
}

func killProcess(cmd *exec.Cmd) {
	if cmd.Process != nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
}

// clearLeftovers stops JobAssist services left behind by a copy that didn't shut down.
func clearLeftovers() {
	_ = exec.Command("pkill", "-f", "uvicorn jobassist.Microservices").Run()
	time.Sleep(3 * time.Second)
	_ = exec.Command("pkill", "-9", "-f", "uvicorn jobassist.Microservices").Run()
	time.Sleep(time.Second)
}

func openBrowser(url string) {
	_ = exec.Command("open", url).Start()
}
