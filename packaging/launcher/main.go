// Command JobAssist starts JobAssist and opens it in the web browser.
//
// Double-click it inside the downloaded JobAssist folder: "JobAssist for Windows.exe" on
// Windows, "JobAssist for Mac" on a Mac. The first run installs what JobAssist needs and asks for API keys;
// after that it starts in a few seconds. Keep its window open while you use JobAssist;
// close the window (or press Ctrl+C) to stop it.
//
// It does what "Start JobAssist.command" does, in one program for both systems:
// install uv if needed, ask for keys once (saved to .env next to it), install the Python
// components and the browser used to read company websites, then start the services,
// open http://localhost:8000 and watch them until the window is closed.
package main

import (
	"bufio"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"time"
)

const appURL = "http://localhost:8000"

type service struct {
	name string
	port int
}

// Started in this order; the job_recommender hosts the cache the others use.
var services = []service{
	{"job_recommender", 8003},
	{"web_scraper", 8001},
	{"data_cleaner", 8002},
	{"cv_feedback_provider", 8004},
	{"list_builder", 8005},
	{"frontend", 8000},
}

// Services whose /health must answer before the page is opened.
var healthPorts = []int{8000, 8001, 8002, 8003, 8005}

var input = bufio.NewReader(os.Stdin)

func say(format string, args ...any) {
	fmt.Printf("\n"+format+"\n", args...)
}

func ask(prompt string) string {
	fmt.Print("\n" + prompt + " ")
	line, _ := input.ReadString('\n')
	return strings.TrimSpace(line)
}

// pause keeps the window open so a message can be read before it closes.
func pause() {
	fmt.Print("\nPress Enter to close this window. ")
	_, _ = input.ReadString('\n')
}

func main() {
	if err := run(); err != nil {
		say("%v", err)
		pause()
		os.Exit(1)
	}
}

// appDirectory is the folder this program sits in (the downloaded JobAssist folder).
func appDirectory() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	if resolved, err := filepath.EvalSymlinks(exe); err == nil {
		exe = resolved
	}
	return filepath.Dir(exe), nil
}

func run() error {
	appDir, err := appDirectory()
	if err != nil {
		return fmt.Errorf("couldn't work out where JobAssist is: %w", err)
	}
	if _, err := os.Stat(filepath.Join(appDir, "pyproject.toml")); err != nil {
		return errors.New("JobAssist's files aren't next to this program. Keep it inside the " +
			"JobAssist folder you downloaded (unzip the whole folder first) and try again.")
	}
	home, _ := os.UserHomeDir()
	logDir := filepath.Join(home, ".jobassist", "logs")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return fmt.Errorf("couldn't create %s: %w", logDir, err)
	}

	say("JobAssist")
	uv, err := ensureUV(home)
	if err != nil {
		return err
	}
	if err := ensureKeys(filepath.Join(appDir, ".env")); err != nil {
		return err
	}
	if err := prepare(appDir, uv, home, logDir); err != nil {
		return err
	}

	// Already running in another window? Just open it — never stop another window's copy.
	if healthy(8000) {
		openBrowser(appURL)
		say("JobAssist is already running in another window, so it has been opened in your browser.")
		say("You can close this window — the other one keeps JobAssist running.")
		pause()
		return nil
	}
	if anyServiceAnswering() {
		say("Clearing up a previous JobAssist that didn't close properly…")
		clearLeftovers()
	}

	return serve(appDir, uv, logDir)
}

// --- Setup -------------------------------------------------------------------

func findUV(home string) string {
	name := "uv"
	if isWindows {
		name = "uv.exe"
	}
	if path, err := exec.LookPath(name); err == nil {
		return path
	}
	for _, dir := range []string{
		filepath.Join(home, ".local", "bin"),
		filepath.Join(home, ".cargo", "bin"),
		"/opt/homebrew/bin",
		"/usr/local/bin",
	} {
		candidate := filepath.Join(dir, name)
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return ""
}

func ensureUV(home string) (string, error) {
	if uv := findUV(home); uv != "" {
		return uv, nil
	}
	say("JobAssist needs a small free tool called 'uv' (from astral.sh) to run.")
	if answer := strings.ToLower(ask("Install it now? [y/n]")); answer != "y" && answer != "yes" {
		return "", errors.New("JobAssist can't start without uv. Run JobAssist again to install it.")
	}
	cmd := uvInstallCommand()
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		return "", errors.New("installing uv failed. Check your internet connection and try again")
	}
	if uv := findUV(home); uv != "" {
		return uv, nil
	}
	return "", errors.New("uv was installed but couldn't be found. Close this window and run " +
		"JobAssist again")
}

func readEnv(path string) map[string]string {
	values := map[string]string{}
	data, err := os.ReadFile(path)
	if err != nil {
		return values
	}
	for _, line := range strings.Split(string(data), "\n") {
		key, value, found := strings.Cut(strings.TrimSpace(line), "=")
		value = strings.TrimSpace(value)
		// Placeholders from .env.example ("your_..._here") count as not set.
		if found && !strings.HasPrefix(key, "#") && !strings.HasPrefix(value, "your_") {
			values[strings.TrimSpace(key)] = value
		}
	}
	return values
}

func ensureKeys(envPath string) error {
	if readEnv(envPath)["ANTHROPIC_API_KEY"] != "" {
		return nil
	}
	say("First-time setup. JobAssist uses Claude to read job pages and score them against your CV.")
	say("Paste your Anthropic API key (from https://console.anthropic.com — it starts with " +
		"sk-ant-).\nIt is saved only in the .env file in this folder.")
	key := ask("Anthropic API key:")
	if key == "" {
		return errors.New("no key entered. Run JobAssist again when you have one")
	}
	if !strings.HasPrefix(key, "sk-ant-") {
		say("That doesn't look like an Anthropic key (they start with sk-ant-), but it has been " +
			"saved. If searches fail, edit the .env file in this folder.")
	}
	lines := []string{"ANTHROPIC_API_KEY=" + key}
	say("Optional: free Adzuna keys add many more job listings (https://developer.adzuna.com).")
	if id := ask("Adzuna app ID (press Enter to skip):"); id != "" {
		lines = append(lines, "ADZUNA_APP_ID="+id, "ADZUNA_APP_KEY="+ask("Adzuna app key:"))
	}
	if reed := ask("Reed API key (optional, https://www.reed.co.uk/developers — Enter to skip):"); reed != "" {
		lines = append(lines, "REED_API_KEY="+reed)
	}

	existing, _ := os.ReadFile(envPath)
	text := string(existing)
	if text != "" && !strings.HasSuffix(text, "\n") {
		text += "\n"
	}
	text += strings.Join(lines, "\n") + "\n"
	if err := os.WriteFile(envPath, []byte(text), 0o600); err != nil {
		return fmt.Errorf("couldn't save the keys to %s: %w", envPath, err)
	}
	say("Saved. You won't be asked again (the keys are in the .env file in this folder).")
	return nil
}

// prepare installs the Python components and, once, the browser for company websites.
func prepare(appDir, uv, home, logDir string) error {
	setupLog := filepath.Join(logDir, "setup.log")
	say("Getting JobAssist ready… (the first time takes a few minutes)")
	if err := runLogged(appDir, setupLog, uv, "sync", "--quiet"); err != nil {
		return fmt.Errorf("couldn't install JobAssist's components. Check your internet "+
			"connection (details: %s)", setupLog)
	}
	marker := filepath.Join(home, ".jobassist", ".browser-installed")
	if _, err := os.Stat(marker); err == nil {
		return nil
	}
	say("One-time setup: installing the browser JobAssist uses to read company websites…")
	if err := runLogged(appDir, setupLog, uv, "run", "playwright", "install", "chromium"); err != nil {
		say("Note: the browser didn't install, so some company websites will be skipped.")
		return nil
	}
	_ = os.WriteFile(marker, nil, 0o644)
	return nil
}

func runLogged(dir, logPath, name string, args ...string) error {
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer logFile.Close()
	cmd := exec.Command(name, args...)
	cmd.Dir = dir
	cmd.Stdout, cmd.Stderr = logFile, logFile
	return cmd.Run()
}

// --- Running -----------------------------------------------------------------

func healthy(port int) bool {
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/health", port))
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

func anyServiceAnswering() bool {
	for _, s := range services {
		if healthy(s.port) {
			return true
		}
	}
	return false
}

type running struct {
	service
	cmd  *exec.Cmd
	done chan error
}

func serve(appDir, uv, logDir string) error {
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, stopSignals...)

	var started []*running
	stopAll := func() {
		say("Stopping JobAssist…")
		for _, r := range started {
			stopProcess(r.cmd)
		}
		deadline := time.After(6 * time.Second)
		for _, r := range started {
			select {
			case <-r.done:
			case <-deadline:
			}
		}
		for _, r := range started {
			killProcess(r.cmd)
		}
		say("JobAssist has stopped.")
	}

	env := append(os.Environ(), "JOB_RECOMMENDER_URL=http://localhost:8003")
	for _, s := range services {
		logFile, err := os.Create(filepath.Join(logDir, s.name+".log"))
		if err != nil {
			stopAll()
			return fmt.Errorf("couldn't write logs to %s: %w", logDir, err)
		}
		cmd := exec.Command(uv, "run", "--env-file", ".env", "uvicorn",
			"jobassist.Microservices."+s.name+".api:app",
			"--host", "127.0.0.1", "--port", fmt.Sprint(s.port),
			"--timeout-graceful-shutdown", "3")
		cmd.Dir = appDir
		cmd.Env = env
		cmd.Stdout, cmd.Stderr = logFile, logFile
		setProcessGroup(cmd)
		if err := cmd.Start(); err != nil {
			logFile.Close()
			stopAll()
			return fmt.Errorf("couldn't start JobAssist (%s): %w", s.name, err)
		}
		r := &running{service: s, cmd: cmd, done: make(chan error, 1)}
		go func(r *running, logFile *os.File) {
			r.done <- r.cmd.Wait()
			logFile.Close()
		}(r, logFile)
		started = append(started, r)
	}

	if !waitUntilHealthy(90*time.Second, signals) {
		stopAll()
		return fmt.Errorf("JobAssist didn't start. Details are in %s", logDir)
	}
	openBrowser(appURL)
	say("JobAssist is running at %s (it should have opened in your browser).", appURL)
	say("Keep this window open while you use it. To stop JobAssist, close this window or press Ctrl+C.")

	// Watch: stop on a signal, or if any service stops on its own.
	exited := make(chan *running, len(started))
	for _, r := range started {
		go func(r *running) {
			err := <-r.done
			r.done <- err // leave it readable for stopAll
			exited <- r
		}(r)
	}
	select {
	case <-signals:
		stopAll()
		return nil
	case r := <-exited:
		say("The %s part of JobAssist stopped unexpectedly. Details: %s", r.name,
			filepath.Join(logDir, r.name+".log"))
		stopAll()
		say("Start JobAssist again to carry on.")
		pause()
		return nil
	}
}

func waitUntilHealthy(limit time.Duration, signals <-chan os.Signal) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		up := 0
		for _, port := range healthPorts {
			if healthy(port) {
				up++
			}
		}
		if up == len(healthPorts) {
			return true
		}
		select {
		case <-signals:
			return false
		case <-time.After(time.Second):
		}
	}
	return false
}
