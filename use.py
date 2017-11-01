#!/usr/bin/env python2

import sys, os, json, platform
import subprocess, string, re

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

def list_separator():
    if os.name == 'nt':
        return ';'
    return ':'

def to_native_path(path):
    path = os.path.abspath(path)
    if path.endswith("\\") or (path.endswith('/') and path != '/'):
        path = path[:-1]
    return path

def fill_placeholders(value):
    placeholders = re.findall('\$\{(.*?)\}', value) # searches for ${foo}
    for placeholder in placeholders:
        if placeholder in os.environ:
            value = value.replace("${" + placeholder + "}", os.environ[placeholder])

    return value

class EnvVariable:
    def __init__(self):
        self.name = ""
        self.value = ""
        self.values = []
    def isPath(self):
        return self.values or '/' in self.value or '\\' in self.value

class Target:
    def __init__(self, tname):
        self.name = tname
        self.uses = []
        self.uses_after = []
        self.cwd = ""
        self.hidden = False
        self.yakuake_tab_name = ""
        self.platforms = []
        self.variables = []

        self.loadJson()

    def jsonFileName(self):
        return _targets_folder + "/../unified/" + self.name + ".json"

    def env_var_from_json(self, json):
        var = EnvVariable()
        key = json.keys()[0]
        var.name = key
        value = json[key]
        value_is_list = type(value) == type([])

        if value_is_list:
            var.values = value
        else:
            var.value = str(value)

        return var

    def loadJson(self):
        if not os.path.exists(self.jsonFileName()):
            return False
        return self.loadJsonFile(self.jsonFileName())

    def loadJsonFile(self, filename):
        if not os.path.exists(filename):
            print "File doesn't exist: " + filename
            return False

        f = open(filename, 'r')
        # print "Processing " + filename
        contents = f.read()
        f.close()
        decoded = json.loads(contents)
        if "os_specific" in decoded:
            if os.name in decoded["os_specific"]:
                for env_var in decoded["os_specific"][os.name]:
                    self.variables.append(self.env_var_from_json(env_var))

        if "env_variables" in decoded:
            for env_var in decoded["env_variables"]:
                self.variables.append(self.env_var_from_json(env_var))

        if "includes" in decoded:
            for include in decoded['includes']:
                if not self.loadJsonFile(fill_placeholders(include)):
                    return False
        return True

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
            name = ""
            if "name" in target:
                name = target['name']
            else:
                print "Missing name for target"
                return False

            t = Target(name)

            if "uses" in target:
                t.uses = target['uses']

            if "uses_after" in target:
                t.uses_after = target['uses_after']

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

def isMacOS():
    return platform.system() == "Darwin"

def source_single_json(target):
    for v in target.variables:
        if not v.name:
            continue

        if v.value:
            value = fill_placeholders(v.value)
            if v.isPath():
                value = to_native_path(value)
            os.environ[v.name] = value
        else: # list case
            value = list_separator()
            for list_token in v.values:
                list_token = fill_placeholders(list_token)
                if v.isPath():
                    list_token = to_native_path(list_token)
                value = value + list_separator() + list_token

            os.environ[v.name] = value.strip(list_separator())

def source_single_file(filename, arguments_for_target):
    command = ""

    filename_cmd = filename
    if arguments_for_target:
        filename_cmd = filename_cmd + " " + arguments_for_target

    shell = shellForOS()
    if shell == 'cmd':
        command = ['cmd', '/C', filename_cmd + ' && set']
        # os.environ['PROMPT'] = ""
    else:
        command = [shell, '-c', 'source ' + filename_cmd + ' && env']

    # print "Sourcing " + filename
    proc = subprocess.Popen(command, stdout = subprocess.PIPE)

    print "Sourcing " + to_native_path(filename_cmd)

    for line in proc.stdout:
        (key, _, value) = line.partition("=")
        if key and not key.startswith('BASH_FUNC_'):
            try:
                os.environ[key] = value.strip()
            except:
                print "Error importing key=" + key + "; with value=" + value.strip()
                throw
    proc.communicate()

    return True

def extensionForScript():
    if isWindows():
        return ".bat"
    return ".source"

def filenameForTarget(target):
    filename = _targets_folder + "/" + target.name + extensionForScript()

    if os.path.exists(target.jsonFileName()):
        if os.path.exists(filename):
            print "Favoring .json over " + filename

        return target.jsonFileName()

    return filename

def currentTargets():
    targets = os.getenv('USE_CURRENT_TARGETS')
    if not targets:
        return []
    return targets.split(';')

def currentTargetsStr():
    return string.join(currentTargets(), ' ');

def shellForOS():
    if 'SHELL' in os.environ:
        return os.environ['SHELL']

    if isWindows():
        return 'cmd'

    return 'bash'

def run_shell(cwd):
    cmd = ""
    shell =  shellForOS()
    if _rcfile and 'bash' in shell:
        cmd = shell + " --rcfile " + _rcfile
    else:
        cmd = shell

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

    filename = filenameForTarget(target)

    if filename.endswith(".json"):
        print "Sourcing " + to_native_path(filename)
        source_single_json(target)
    else:
        if os.path.exists(filename):
            source_single_file(filename, arguments_for_target)

    newCurTargets = string.join(currentTargets(), ';')

    os.environ['USE_CURRENT_TARGETS'] = newCurTargets + ";" + target.name
    os.environ['USE_CURRENT_TARGET_ARGS'] = ""

    if arguments_for_target:
        os.environ['USE_CURRENT_TARGET_ARGS'] = arguments_for_target

    for targetName in target.uses_after:
        if not source_target(getTarget(targetName), []):
            return False

    return True

def reset_env():
    os.environ['USE_CURRENT_TARGETS'] = ""
    os.environ['USE_CURRENT_TARGET_ARGS'] = ""
    return source_target(getTarget("default"), [])

def use_target(target, arguments_for_target):
    global _switches
    if is_sourced(target.name, arguments_for_target):
        return True

    if '--keep' not in _switches:
        if not reset_env(): # source default.source
            return False

    # run qdbus before sourcing, otherwise it might use an incompatible Qt
    must_restore_yakuake = False
    if target.yakuake_tab_name and not isMacOS():
        os.system("rename_yatab.sh " + target.yakuake_tab_name)
        must_restore_yakuake = True

    success = False
    if source_target(target, arguments_for_target):
        success = run_shell(cleanup_cwd(target.cwd)) # this hangs here until user exits bash
    else:
        success = False

    if must_restore_yakuake:
        os.system("rename_yatab.sh Shell")

    return success

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

def source_default():
    t = Target("default")
    _targets[t.name] = t

process_arguments()

if '--config' in _switches or '--configure' in _switches or '--conf' in _switches:
    open_editor(_json_config_file)
    sys.exit(1)

source_default()

if not loadJson():
    print "Error loading json"
    sys.exit(1)

if len(sys.argv) == 1:
    print currentTargetsStr()
    sys.exit(-1)

_targetName = sys.argv[1]

if '--edit' in _switches:
    filename = filenameForTarget(Target(_targetName))
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
