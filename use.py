#!/usr/bin/env python2

import sys, os, json, platform
import subprocess, string

_json_config_file = os.getenv('USE_CONFIG_FILE')
_targets_folder = os.getenv('USE_TARGETS_FOLDER')
_targets = {}
_rcfile = ""
_arguments = sys.argv[1:]
_configure = False
_switches = []

POSSIBLE_SWITCHES = ['--keep', '--config', '--configure', '--edit', '--conf', '--help', '-h', '--bash-autocomplete-helper']

if not _json_config_file:
    print "Configuration file not found!\nSet the env variable USE_CONFIG_FILE, point it to your json file.\n"
    sys.exit(-1)

if not _targets_folder:
    print "Use folder not found!\nSet env variable USE_TARGETS_FOLDER, point it to your folder with env scripts.\n"
    sys.exit(-1)

class Target:
    def __init__(self):
        self.name = ""
        self.uses = []
        self.cwd = ""
        self.hidden = False
        self.yakuake_tab_name = ""
        self.platforms = []

def printUsage():
    print "Usage:"
    print sys.argv[0] + " <target>\n"

    print "Available targets:\n"
    for target in _targets:
        t = _targets[target]
        if not t.hidden:
            print "  " + target

    sys.exit(1)

def cleanup_cwd(cwd):
    if cwd.startswith("$"):
        env_var_name = cwd[1:]
        if env_var_name and env_var_name in os.environ:
            return os.environ[env_var_name]
    return cwd

def loadJson():
    f = open(_json_config_file, 'r')
    contents = f.read()
    f.close()

    decoded = json.loads(contents)

    global _rcfile

    if "targets" in decoded:
        for target in decoded['targets']:
            t = Target()
            if "name" in target:
                t.name = target['name']
            else:
                print "Missing name for target"
                return False

            if "uses" in target:
                t.uses = target['uses']

            if "cwd" in target:
                t.cwd = target['cwd']

            if "rename_yakuake_to" in target:
                t.yakuake_tab_name = target['rename_yakuake_to']

            if "hidden" in target:
                t.hidden = target['hidden']

            _targets[t.name] = t

    if "rcfile" in decoded:
        _rcfile = decoded['rcfile']
        if not os.path.exists(_rcfile):
            return False

    return True;

def getTarget(name):
    if name in _targets:
        return _targets[name]
    else:
        print "Unknown target: " + name
        printUsage()

def platform_name():
    plat = platform.system()
    if plat == "Linux":
        return "linux"
    elif plat == "Windows":
        return "windows"
    elif plat == "Darwin":
        return "osx"
    else:
        print "Unsupported platform"
        sys.exit(-1)

def isWindows():
    return platform_name() == "windows"

def source_single_file(filename, arguments_for_target):
    command = ""

    filename_cmd = filename
    if arguments_for_target:
        filename_cmd = filename_cmd + " " + arguments_for_target

    if isWindows():
        command = ['cmd', '/C', filename_cmd + ' && set']
        # os.environ['PROMPT'] = ""
    else:
        command = ['bash', '-c', 'source ' + filename_cmd + ' && env']

    # print "Sourcing " + filename
    proc = subprocess.Popen(command, stdout = subprocess.PIPE)

    print "Running " + filename_cmd

    for line in proc.stdout:
        (key, _, value) = line.partition("=")
        os.environ[key] = value.strip()
    proc.communicate()

    return True

def extensionForScript():
    if isWindows():
        return ".bat"
    return ".source"

def filenameForTarget(targetName):
    return _targets_folder + "/" + targetName + extensionForScript()

def currentTargets():
    targets = os.getenv('USE_CURRENT_TARGETS')
    if not targets:
        return []
    return targets.split(';')

def currentTargetsStr():
    return string.join(currentTargets(), ' ');

def shellForOS():
    if isWindows():
        return 'cmd'
    return 'bash'

def run_bash(cwd):
    cmd = ""
    if _rcfile and not isWindows(): # Windows sources the alias automatically
        cmd = "bash --rcfile " + _rcfile
    else:
        cmd = shellForOS()

    # print "Running: " + cmd
    old_cwd = ""
    if cwd:
        old_cwd = os.getcwd()
        os.chdir(cwd)
    result = True
    try:
        result = os.system(cmd) == 0
    except:
        pass

    if cwd:
        os.chdir(old_cwd)

    return result

def is_sourced(targetName, arguments_for_target):
    if targetName not in currentTargets():
        return False

    current_target_args = ""
    if 'USE_CURRENT_TARGET_ARGS' in os.environ:
        current_target_args = os.environ['USE_CURRENT_TARGET_ARGS']

    return current_target_args == arguments_for_target

def source_target(target, arguments_for_target):
    if target.name in currentTargets():
        return True

    for targetName in target.uses:
        if not source_target(getTarget(targetName), []):
            return False

    filename = filenameForTarget(target.name)
    if os.path.exists(filename):
        source_single_file(filename, arguments_for_target)
    elif not target.cwd:
        # No source file and no dir to change; nothing to do.
        print "File doesn't exist " + filename
        return False

    newCurTargets = string.join(currentTargets(), ';')

    os.environ['USE_CURRENT_TARGETS'] = newCurTargets + ";" + target.name
    os.environ['USE_CURRENT_TARGET_ARGS'] = ""

    if arguments_for_target:
        os.environ['USE_CURRENT_TARGET_ARGS'] = arguments_for_target

    return True

def reset_env():
    os.environ['USE_CURRENT_TARGETS'] = ""
    os.environ['USE_CURRENT_TARGET_ARGS'] = ""
    return source_target(getTarget("core"), [])

def use_target(target, arguments_for_target):
    global _switches
    if is_sourced(target.name, arguments_for_target):
        return True

    if '--keep' not in _switches:
        if not reset_env(): # source core.source
            return False

    if source_target(target, arguments_for_target):
        if target.yakuake_tab_name:
            os.system("rename_yatab.sh " + target.yakuake_tab_name)
        success = run_bash(cleanup_cwd(target.cwd)) # this hangs here until user exits bash
        if target.yakuake_tab_name:
            os.system("rename_yatab.sh Shell") # restore to something generic
        return success
    else:
        return False

def editor():
    ed = os.getenv('USE_EDITOR')
    if ed:
        return ed
    return 'kate'

def open_editor(filename):
    return os.system(editor() + " " + filename) == 0

def process_arguments():
    global _switches
    for a in _arguments:
        if a in POSSIBLE_SWITCHES:
            _arguments.remove(a)
            _switches.append(a)
        elif a.startswith('--') and not '--bash-autocomplete-helper' in _arguments:
            print "Invalid switch: " + a
            sys.exit(-1)

def source_core():
    t = Target()
    t.name = "core"
    _targets[t.name] = t

process_arguments()

if '--config' in _switches or '--configure' in _switches or '--conf' in _switches:
    open_editor(_json_config_file)
    sys.exit(1)

source_core()

if not loadJson():
    print "Error loading json"
    sys.exit(1)

if len(sys.argv) == 1:
    print currentTargetsStr()
    sys.exit(-1)

_targetName = sys.argv[1]

if '--edit' in _switches:
    filename = filenameForTarget(_targetName)
    print "Opening editor for " + filename
    if not open_editor(filename):
        print "Error opening editor"
    sys.exit(0)

if '--help' in _switches or '-h' in _switches:
    printUsage()
    sys.exit(0)

if '--bash-autocomplete-helper' in _switches:
    result = ''
    wordBeginning = ""
    if _arguments:
        wordBeginning = _arguments[0]

    for target in _targets:
        t = _targets[target]
        if not t.hidden and target.startswith(wordBeginning):
            result = result + ' ' + target

    if wordBeginning.startswith('-'):
        # Let's only spam the completion with switches if the user already typed -
        for s in POSSIBLE_SWITCHES:
            if s.startswith(wordBeginning):
                result = result + ' ' + s

    print result.strip()
    sys.exit(0)


arguments_for_target = string.join(_arguments[1:], " ")
use_target(getTarget(_targetName), arguments_for_target)
