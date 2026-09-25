#!/usr/bin/python3
"""
Starting the SDR program, and knowing whose it is.

THE RULE, which decides everything here:

    An SDR that was ALREADY RUNNING is the operator's. This application
    attaches to it and leaves it running when it closes.

    An SDR this application STARTED is its own, and is closed with it.

Nothing else would do. Quitting a control panel should not take down a
receiver somebody was listening to; and leaving a window behind that nobody
opened deliberately is just as rude in the other direction.

Modelled on the launching the previous version did for SDR++ -- the process
scan, binding to an existing instance, and terminating only a spawned one --
generalised to each program this can drive, since they live in different
places and take different arguments.

WHERE THE PROGRAMS LIVE is a guess per platform, and guesses go stale: a
Windows install in particular lands wherever the operator chose. The "SDR
Path" setting overrides it, and the Setup page asks for one when the guess
fails.
"""
import os
import shutil
import time
import subprocess
import sys

# WHERE THE PROGRAMS LIVE IS IN sdr_programs.json NOW, beside everything else
# that is true of a program rather than of this station -- its port, its mode
# names, what it cannot do. This module takes a Profile and starts what it
# describes; it knows nothing about any particular program.


def _system():
    return "win32" if sys.platform.startswith("win") else (
        "darwin" if sys.platform == "darwin" else "linux")


def running_process(profile):
    """
    The process of an SDR already running, or None.

    Uses psutil where it is installed -- the previous version's approach, and
    the dependable one -- and falls back to asking the system, so a missing
    package means a worse answer rather than no feature.
    """
    names = {name.lower() for name in profile.process_names}
    if not names:
        return None

    try:
        import psutil
    except ImportError:
        return _running_without_psutil(names)

    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = (process.info["name"] or "").lower()
            if name in names:
                return process
        except Exception:
            continue                    # gone, or not ours to look at
    return None


def _running_without_psutil(names):
    """
    Whether one of these names is running, asking the system.

    Returns True rather than a process: without psutil there is nothing to
    hold on to, and True is enough to decide not to start another.
    """
    try:
        if _system() == "win32":
            output = subprocess.check_output(["tasklist"], text=True,
                                             stderr=subprocess.DEVNULL)
        else:
            output = subprocess.check_output(["ps", "-A", "-o", "comm"], text=True,
                                             stderr=subprocess.DEVNULL)
    except Exception:
        return None
    lowered = output.lower()
    return True if any(name in lowered for name in names) else None


def program_command(profile, override=""):
    """
    What to run, as a list -- or None if it cannot be found.

    `override` is the "SDR Path" setting. It may be a bare path, or a whole
    command line for something like rigctld that needs arguments; either is
    accepted.
    """
    system = _system()
    if override:
        parts = override.split() if " " in override and not os.path.exists(override) \
            else [override]
        found = parts[0] if os.path.exists(parts[0]) else shutil.which(parts[0])
        return [found] + parts[1:] if found else None

    for candidate in profile.launch_paths(system):
        found = candidate if os.path.exists(candidate) else shutil.which(candidate)
        if found:
            return [found] + list(profile.launch_arguments(system))
    return None


class Started:
    """
    A program this application started, however it was started.

    Not always a Popen. On macOS a program that must be quit politely is
    launched as an APPLICATION -- "open -a Gqrx" -- and `open` exits at once,
    so what it started has to be found afterwards and held by its process id
    instead. Both kinds answer the same three questions: is it still there,
    will it go when asked, and will it go when told.
    """

    def __init__(self, profile, popen=None, pid=None):
        self.profile = profile
        self.popen = popen
        self.pid = pid if pid is not None else (popen.pid if popen else None)

    def is_running(self):
        if self.popen is not None:
            return self.popen.poll() is None
        if self.pid is not None:
            try:
                import psutil
                return psutil.pid_exists(self.pid)
            except ImportError:
                try:
                    os.kill(self.pid, 0)
                    return True
                except OSError:
                    return False
        # NO PROCESS ID, BUT WE STARTED SOMETHING. Launching as an
        # application means `open` exits immediately and the real process has
        # to be found afterwards -- and without psutil it cannot be, so the
        # id stays None. Reading that as "not running" made stop() decide the
        # program had already gone and ask nothing: Gqrx simply stayed open,
        # silently. Look for it by name instead.
        return running_process(self.profile) is not None

    def ask_to_quit(self):
        """
        Asks it to close itself, the way the platform offers. True if there
        was something to ask.
        """
        system = _system()
        try:
            if system == "darwin" and self.profile.app_name:
                # NOT SILENCED. Asking one application to quit another needs
                # Automation permission on macOS, and the first attempt puts
                # up a prompt: refused or unanswered, osascript fails with
                # "Not authorized to send Apple events" and the program
                # simply stays open. Sending that to /dev/null made it look
                # as though nothing had been tried.
                done = subprocess.run(
                    ["osascript", "-e",
                     f'tell application "{self.profile.app_name}" to quit'],
                    capture_output=True, text=True, timeout=10)
                # WHETHER IT WORKED IS NOT THE RETURN CODE'S TO SAY. Gqrx
                # answers a quit with "User canceled (-128)" and then quits
                # anyway. Taking that as a refusal meant declaring failure
                # about a program that had gone -- and, since Gqrx must never
                # be forced, leaving it alone instead of noticing it had
                # already closed. Only whether the process is still there
                # settles it, which the wait below does.
                if done.returncode != 0:
                    complaint = (done.stderr or "").strip()
                    print(f"[sdr] {self.profile.app_name} answered the quit with: "
                          f"{complaint or done.returncode}")
                    if "-1743" in complaint or "not authorized" in complaint.lower():
                        print("[sdr] macOS is blocking it: System Settings -> Privacy "
                              "& Security -> Automation, and allow this application "
                              "to control " + self.profile.app_name)
                return True
            if system == "win32" and self.pid:
                done = subprocess.run(["taskkill", "/PID", str(self.pid)],
                                      capture_output=True, text=True, timeout=10)
                if done.returncode != 0:
                    print(f"[sdr] asking {self.profile.name} to close failed: "
                          f"{(done.stdout or done.stderr or '').strip()}")
                    return False
                return True
        except Exception as err:
            print(f"[sdr] could not ask {self.profile.name} to quit: {err}")
            return False
        return False

    def wait(self, timeout):
        """Whether it has gone within the time."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                return True
            time.sleep(0.2)
        return not self.is_running()

    def insist(self):
        """SIGTERM, then kill. Never called for a program marked never_force_quit."""
        try:
            if self.popen is not None:
                self.popen.terminate()
            elif self.pid:
                os.kill(self.pid, 15)
        except Exception:
            pass
        if self.wait(3.0):
            return True
        try:
            if self.popen is not None:
                self.popen.kill()
            elif self.pid:
                os.kill(self.pid, 9)
        except Exception:
            return False
        return self.wait(2.0)


def start(profile, override=""):
    """
    Starts the SDR program.

    Returns:
        (Started, note) -- what was started, or None, and a sentence for the
        operator either way. The caller keeps the Started: it is what says
        this instance is ours to close.
    """
    if profile.needs_command_line and not override:
        # rigctld has to be told which radio and where, and no guess can
        # supply that. The operator gives the whole command line.
        return None, (f"{profile.name} needs a command line of its own -- "
                      f"set it under the SDR's settings")

    # AS AN APPLICATION where the platform has such a thing and the program
    # needs to be quit politely -- see Profile.launch_as_application.
    if (_system() == "darwin" and profile.launch_as_application
            and profile.app_name and not override):
        try:
            subprocess.run(["open", "-a", profile.app_name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15)
        except Exception as err:
            return None, f"could not start {profile.app_name}: {err}"
        # `open` has exited; find what it started, so there is something to
        # ask to quit later.
        pid = None
        for _ in range(20):
            process = running_process(profile)
            if process is not None:
                pid = getattr(process, "pid", None)
                break
            time.sleep(0.25)
        return Started(profile, pid=pid), f"started {profile.app_name}"

    command = program_command(profile, override)
    if not command:
        where = override or ", ".join(profile.launch_paths()) or "nowhere known"
        return None, f"could not find the program (looked in {where})"
    try:
        popen = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
    except Exception as err:
        return None, f"could not start {command[0]}: {err}"
    return Started(profile, popen=popen), f"started {os.path.basename(command[0])}"


def stop(started, timeout=15.0, force_if_needed=False):
    """
    Closes a program this application started -- POLITELY, and for some
    programs politely or not at all.

    ASKING MATTERS. SIGTERM is not handled by a Qt application unless it was
    written to: it dies where it stands without running its shutdown, so its
    settings are never written properly. Gqrx then reports an unexpected quit
    and can lose which SDR device it was using -- observed, repeatedly, which
    is why its entry says never_force_quit.

    NEVER FORCED means exactly that -- USUALLY. If it will not go when asked,
    it is left running and the operator is told. A window left open is a
    nuisance; a corrupted configuration is an evening.

    force_if_needed BREAKS THAT RULE DELIBERATELY, and only where the rule
    cannot be kept: an SDR dongle belongs to one program at a time, so a
    program that will not let go of it stops the next one from starting at
    all. Switching from one SDR to another is that case. Quitting is not --
    nothing is waiting for the device then, so a stubborn program is left to
    its own settings.

    Returns:
        (closed, note) -- whether it has gone, and what to say about it.
    """
    if started is None or not started.is_running():
        return True, ""

    name = started.profile.name
    if started.ask_to_quit() and started.wait(timeout):
        return True, f"closed {name}"

    if started.profile.never_force_quit and not force_if_needed:
        return False, (f"{name} did not close when asked, and is left running "
                       f"-- forcing it corrupts its settings")

    forced_against_the_rule = started.profile.never_force_quit
    if started.insist():
        if forced_against_the_rule:
            return True, (f"{name} would not close and had to be forced -- it "
                          f"was holding the SDR device, and its own settings "
                          f"may not have been saved")
        return True, f"closed {name}"
    return False, f"{name} would not close, even when forced"
