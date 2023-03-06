#!/usr/bin/env python3

import sys
import os
import json
import platform
import io
import subprocess
import string
import re

_print_env_only = '--print' in sys.argv or '--print-to-file' in sys.argv
_print_env_to_file = '--print-to-file' in sys.argv


def isWindows():
    return platform.system() == "Windows"


def osType():  # returns 'nt' or 'posix'
    return os.name

# Like platformName() but will return "DarwinArm" for Apple Sillicon macs
# Brew for some reason uses /opt in arm64 macs, so we need to distinguish


def platformNameWithArch():
    plat = platform.system()
    if plat == 'Darwin' and platform.machine() == 'arm64':
        return 'DarwinArm'

    return plat


def platformName():  # returns 'Windows', 'Linux' or 'Darwin'
    return platform.system()


def platformNameLowercase():
    return platformName().lower()


def isWSL():
    try:
        f = open('/proc/version', 'r')
        return 'microsoft' in f.read().lower()
    except:
        return False


def isLinux():
    return platform.system() == "Linux"


def isBash():
    return "bash" in os.getenv("SHELL")


def usePlatform():  # returns 'windows' or 'posix'
    if isWindows():
        return 'windows'
    return 'posix'


def fill_placeholders(value):
    placeholders = re.findall('\$\{(.*?)\}', value)  # searches for ${foo}
    for placeholder in placeholders:
        value = value.replace("${" + placeholder + "}", os.getenv(placeholder, ''))

    return value


def to_native_path(path):
    path = os.path.abspath(path)
    if path.endswith("\\") or (path.endswith('/') and path != '/'):
        path = path[:-1]
    return path


def unix_to_native(path):
    if not isWindows():
        return path
    if (path.lower().startswith("/c/") or path.lower() == "/c"):
        path = "C:" + path[2:]
        path = path.replace("/", "\\")
    return path


def to_unix_path(path):
    requiresConversion = isWindows() and isBash()
    if not requiresConversion:
        return path

    if path.lower().startswith("/c/"):
        path = path.replace("\\", "/")

    if path.lower().startswith("c:"):
        path = path.replace("c:", "/c")
        path = path.replace("C:", "/C")
        path = path.replace("\\", "/")

    return path

# Represents the $HOME/.use.conf


class UseConf:
    def __init__(self):
        self.use_targets_folder = ""

        if not self.targetsFolder():
            print("Use folder not found!\nSet 'use_targets_folder' variable in ~/.use.conf, point it to your folder with env scripts.\n")
            sys.exit(-1)
        if not self.targetsJsonFilename():
            print("Configuration file not found!\nSet the env variable USES_LIST_FILE, point it to your json file.\n")
            sys.exit(-1)

        os.environ['USE_TARGETS_FOLDER'] = self.useFolder()

    def useFolder(self):
        if isLinux():
            return '/data/windows-linux-shared/use_scripts'
        elif isWindows():
            return 'c:\\data\\windows-linux-shared\\use_scripts'
        else:
            return '/Users/serj/data/windows-linux-shared/use_scripts'

    def targetsFolder(self):
        if isLinux():
            return '/data/windows-linux-shared/use_scripts/posix'
        elif isWindows():
            return 'c:\\data\\windows-linux-shared\\use_scripts\\windows'
        else:
            return '/Users/serj/data/windows-linux-shared/use_scripts/posix'

    def targetsJsonFilename(self):
        return self.useFolder() + '/targets.json'


_use_conf = UseConf()
_rename_yakuake_tab = os.getenv('USE_YAKUAKE', '') == '1'
_targets = {}
_arguments = sys.argv[1:]
_configure = False
_switches = []
_ask_for_ssh_keys = False
_is_debug = '--debug' in sys.argv
_desired_command = ''
_desired_cwd = ''
_silent = False
_ignore = ''
_env_lines = []

POSSIBLE_SWITCHES = ['--keep', '--config', '--configure', '--edit', '--conf', '--help',
                     '-h', '--bash-autocomplete-helper', '--debug', '--silent', '--print', '--print-to-file']


def list_separator(isForPrinting=False):
    if os.name == 'nt':
        if isBash() and isForPrinting:
            return ':'
        return ';'
    return ':'

# Reads a property from json, but tries several platform suffixes


def read_json_property(propName, json):
    # First try with OS qualification
    # for example, if propName is "cwd", we try "cwd_windows".
    propNameCandiate = propName + "_" + platform.system().lower()

    if propNameCandiate in json:
        return json[propNameCandiate]

    # Now try OS type (posix vs nt), as Linux shared much with macOS
    propNameCandiate = propName + "_" + os.name
    if propNameCandiate in json:
        return json[propNameCandiate]

    # finally, the property without any qualification
    if propName in json:
        return json[propName]

    return None


class EnvVariable:
    def __init__(self):
        self.name = ""
        self.value = ""
        self.values = []

    def isPath(self):
        v = fill_placeholders(self.value)
        if v.startswith('-') or "=" in v:  # Hack, there's not an easy way to check if it's a path
            return False

        return self.values or '/' in v or '\\' in v


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
        self.arg = ""
        self.description = ""
        self.history = False

        self.loadJson()

    def jsonFileName(self):
        return _use_conf.targetsFolder() + "/../" + self.name + ".json"

    def yakuakeTabName(self):
        if self.isGeneric():
            return self.yakuake_tab_name.replace("%", self.arg)
        return self.yakuake_tab_name

    def env_var_from_json(self, json):
        var = EnvVariable()
        key = list(json.keys())[0]
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

    def isGeneric(self):
        return "%" in self.name

    def displayName(self):
        if self.isGeneric() and self.arg:
            return self.name.replace("%", self.arg)
        return self.name

    def simpleName(self):
        if self.isGeneric():
            return self.name.replace("-%", "")
        return self.name

    def loadJsonFile(self, filename):
        if not os.path.exists(filename):
            print("File doesn't exist: " + filename)
            return False

        f = open(filename, 'r')
        # print("Processing " + filename
        contents = f.read()
        f.close()
        decoded = json.loads(contents)

        # first source 'nt' and 'posix'
        if osType() in decoded:
            for env_var in decoded[osType()]:
                self.variables.append(self.env_var_from_json(env_var))

        # now source 'Linux', 'Darwin'or 'Windows', which have precedence

        # Try DarwinArm before the generic Darwin, as Brew on arm uses different install paths
        plat = platformNameWithArch()
        if plat not in decoded:
            plat = platformName()

        if plat in decoded:
            for env_var in decoded[plat]:
                self.variables.append(self.env_var_from_json(env_var))

        if isWSL() and "Windows-WSL" in decoded:
            for env_var in decoded["Windows-WSL"]:
                self.variables.append(self.env_var_from_json(env_var))

        # Source the platform-independent variables
        if "any" in decoded:
            for env_var in decoded["any"]:
                self.variables.append(self.env_var_from_json(env_var))

        if "includes" in decoded:
            for include in decoded['includes']:
                if not self.loadJsonFile(fill_placeholders(include)):
                    return False

        if "description" in decoded:
            self.description = decoded['description']

        return True


def printUsage():
    print("Usage:")
    print(sys.argv[0] + " <target>")
    print(sys.argv[0] + " <target> [--print|--print-to-file] [--command=<command>][--ignore=<target>]\n")

    print("Available targets:\n")
    for target in _targets:
        t = _targets[target]
        if not t.hidden:
            str = "  " + target
            if t.description:
                str += " (" + t.description + ")"
            print(str)
    sys.exit(1)


def cleanup_cwd(cwd):
    return fill_placeholders(cwd)


# Loads targets.json file into _targets variable
def read_targets_json():
    f = open(_use_conf.targetsJsonFilename(), 'r')
    contents = f.read()
    f.close()

    decoded = json.loads(contents)

    global _ask_for_ssh_keys

    if "targets" in decoded:
        for target in decoded['targets']:
            name = ""
            if "name" in target:
                name = target['name']
            else:
                print("Missing name for target")
                return False

            t = Target(name)

            if "history" in target:
                t.history = target['history']

            uses = read_json_property("uses", target)
            if uses is not None:
                t.uses = uses

            if "uses_after" in target:
                t.uses_after = target['uses_after']

            cwd = read_json_property("cwd", target)
            if cwd:
                t.cwd = cwd

            # print("cwd " + str(cwd)

            if "rename_yakuake_to" in target:
                t.yakuake_tab_name = target['rename_yakuake_to']

            if "hidden" in target:
                t.hidden = target['hidden']

            _targets[t.name] = t

    if "ask_for_ssh_keys" in decoded:
        _ask_for_ssh_keys = decoded['ask_for_ssh_keys']

    return True


def getGenericTargetAndArg(name):
    candidates = []
    for targetName in _targets.keys():
        target = _targets[targetName]
        if target.isGeneric():
            targetName = target.simpleName()  # Example "qt-" instead of "qt-%"
            if name.startswith(targetName):
                candidates.append(targetName)

    # Sort candidates by length, so that "qt-mingw-%" matches "qt-mingw-", not "qt-"
    if candidates:
        candidates.sort(key=len, reverse=True)
        arg = name.replace(candidates[0] + "-", "")
        return {"name": candidates[0], "arg": arg}

    return {}


def getTarget(name):
    if name in _targets:
        return _targets[name]

    genericTarget = getGenericTargetAndArg(name)

    if genericTarget and genericTarget["name"] + "-%" in _targets:
        return _targets[genericTarget["name"] + "-%"]

    print("Unknown target: " + name)
    printUsage()


def set_env_variable(key, value):
    os.environ[key] = value
    if _print_env_only:
        line = ""
        if ' ' in value or ';' in value:
            line = f'export {key}="{value}"'
        else:
            line = f'export {key}={value}'
        _env_lines.append(line)


def source_single_json(target):
    global _print_env_only, _is_debug

    for v in target.variables:
        if not v.name:
            continue

        if v.value:
            if v.value == "USE_ARG":
                value = target.arg
            else:
                value = fill_placeholders(v.value)

            if v.isPath():
                if _print_env_only:
                    value = to_unix_path(value)
                else:
                    value = to_native_path(value)

            set_env_variable(v.name, value)

            if _is_debug:
                print("var : " + v.name + "=" + value + " (v.isPath=" + str(v.isPath()) + ")")
        else:  # list case
            value = list_separator()
            for list_token in v.values:
                list_token = fill_placeholders(list_token)
                if v.isPath():
                    if _print_env_only:
                        list_token = to_unix_path(list_token)
                    else:
                        list_token = to_native_path(list_token)

                value = value + list_separator(_print_env_only) + list_token

            set_env_variable(v.name, value.strip(';').strip('.'))


def source_single_file(filename):
    global _silent
    command = ""

    filename_cmd = filename

    shell = shellForOS(filename)
    if shell == 'cmd':
        command = ['cmd', '/C', filename_cmd + ' && set']
        # os.environ['PROMPT'] = ""
    else:
        command = [shell, '-c', 'source ' + filename_cmd + ' && env']

    proc = subprocess.Popen(command, stdout=subprocess.PIPE)

    if not _silent:
        print("Sourcing " + to_native_path(filename_cmd))

    # for line in io.TextIOWrapper(proc.stdout, encoding="utf-8"):
    for line in proc.stdout:
        foo = line.decode('utf-8').partition("=")
        (key, _, value) = foo
        if key and not key.startswith('BASH_FUNC_'):
            try:
                set_env_variable(key, value.strip())
            except:
                print("Error importing key=" + key + "; with value=" + value.strip())
                raise
    proc.communicate()

    return True


def extensionForScript():
    if isWindows():
        return ".bat"
    return ".source"


def filenameForTarget(target):
    filename = _use_conf.targetsFolder() + "/" + target.name + extensionForScript()
    if os.path.exists(target.jsonFileName()) or target.isGeneric():
        if os.path.exists(filename):
            print("Favoring .json over " + filename)

        return target.jsonFileName()

    return filename


def currentTargets():
    targets = os.getenv('USE_CURRENT_TARGETS')
    if not targets:
        return []
    return targets.split(';')


def currentTargetsStr():
    return ' '.join(currentTargets())


def shellForOS(filename=""):
    # .bat files are always sourced by cmd. Use .json if you don't like this
    if filename.endswith(".bat") or filename.endswith(".cmd"):
        return 'cmd'

    envShell = os.getenv('SHELL')
    if _is_debug:
        print("shell=" + envShell)

    # Workaround Git Bash bug on Windows, where it prepends the current cwd:
    if envShell is not None:
        if envShell.endswith('/bash') or envShell.endswith('\\bash'):
            envShell = 'bash'

    if envShell and envShell != '/bin/false':
        return envShell

    if isWindows():
        return 'cmd'

    return 'bash'


def run_command(cmd):
    return os.system(cmd) == 0


def run_shell(cwd):
    global _is_debug
    if _is_debug:
        print("run_shell: cwd=" + cwd)

    cmd = ""
    shell = shellForOS()
    cmd = shell

    if _is_debug:
        print("run_shell: cmd=" + cmd)

    old_cwd = ""
    if cwd:
        if os.path.exists(cwd):
            old_cwd = os.getcwd()
            os.chdir(cwd)
        else:
            print("cwd Path doesn't exist: " + cwd)
    result = True
    try:
        if _is_debug:
            print('Running ' + cmd)

        result = run_command(cmd)
    except:
        pass

    if cwd:
        os.chdir(old_cwd)

    return result


def is_sourced(target):
    if target.displayName() not in currentTargets():
        return False

    return True


def history_folder():
    return os.getenv('USE_HISTORY_FOLDER', '')


def envFile():
    if isWindows():
        return "c:\\data\\use.env"
    return "/tmp/use.env"


def print_target(target):
    global _print_env_to_file, _silent

    # simpler to just reuse source_target, as it has some business logic
    source_target(target)

    cwd = cleanup_cwd(target.cwd)
    if cwd:
        _env_lines.append(f'export PWD="{cwd}"')

    # --print prints to stdout, while --print-to-file prints to file
    if _print_env_to_file:
        with open(envFile(), "w") as f:
            for line in _env_lines:
                f.write(line + "\n")
    else:
        for line in _env_lines:
            print(line)


def source_target(target):
    global _silent
    if target.name in currentTargets():
        return True

    for targetName in target.uses:
        if targetName == _ignore:
            # user passed --ignore=foo
            continue

        targetToUse = getTarget(targetName)
        generic = getGenericTargetAndArg(targetName)
        if generic and generic['arg'] != '%':
            # Argument is already set, so use it. For example
            # 'qt-installer-mingw-%' uses 'mingw64-730', so use 730 for mingw64, instead of the top-level argument passed (5.14.2 for example)
            targetToUse.arg = generic['arg']

        if not source_target(targetToUse):
            return False

    filename = filenameForTarget(target)

    if filename.endswith(".json"):
        arg = ""
        if target.arg:
            arg = " " + target.arg
        if not _silent:
            print("Sourcing " + to_native_path(filename) + arg)
        source_single_json(target)
    else:
        if os.path.exists(filename):
            source_single_file(filename)

    newCurTargets = ';'.join(currentTargets())

    set_env_variable('USE_CURRENT_TARGETS', newCurTargets + ";" + target.displayName())

    hist_folder = history_folder()
    if hist_folder and target.history:
        set_env_variable('HISTFILE', hist_folder + '/' + target.name + '.hist')

    for targetName in target.uses_after:
        if not source_target(getTarget(targetName)):
            return False

    return True


def reset_env():
    os.environ['USE_CURRENT_TARGETS'] = ""
    return source_target(getTarget("default"))


def run_shell_for_target(target):
    global _switches, _rename_yakuake_tab, _desired_command, _desired_cwd

    # run qdbus before sourcing, otherwise it might use an incompatible Qt
    must_restore_yakuake = False
    if target.yakuake_tab_name and _rename_yakuake_tab:
        os.system("rename_yatab.sh " + target.yakuakeTabName())
        must_restore_yakuake = True

    success = False
    if source_target(target):
        if _is_debug:
            print("cwd=" + target.cwd)
            print("cleanup_cwd(target.cwd)=" + cleanup_cwd(target.cwd))
        if _desired_command:
            if _desired_cwd:
                os.chdir(_desired_cwd)
            # When --command=foo is passed, we run foo with the desired env, instead of opening an hanging shell
            if _is_debug:
                print("Desired Command=" + _desired_command + " ; _desired_cwd=" + _desired_cwd)
            success = run_command(_desired_command)
        else:
            success = run_shell(cleanup_cwd(target.cwd))  # this hangs here until user exits bash
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
    global _switches, _desired_command, _desired_cwd, _silent, _ignore
    argscopy = _arguments.copy()

    for a in argscopy:
        if a in POSSIBLE_SWITCHES:
            _arguments.remove(a)
            _switches.append(a)
        elif a.startswith('--command='):
            _desired_command = a.split('--command=')[1]
            _arguments.remove(a)
        elif a.startswith('--cwd='):
            _desired_cwd = a.split('--cwd=')[1]
            _arguments.remove(a)
        elif a.startswith('--ignore='):
            _ignore = a.split('--ignore=')[1]
            _arguments.remove(a)
        elif a.startswith('--') and not '--bash-autocomplete-helper' in _arguments:
            print("Invalid switch: " + a)
            sys.exit(-1)
    _silent = '--silent' in _switches


def read_default_json():
    t = Target("default")
    _targets[t.name] = t


def ask_for_ssh_keys():
    try:
        subprocess.check_output(["ssh-add", "-L"]) == 0
    except:
        return os.system("ssh-add") == 0

    return True


def first_generic_target(targetName):
    if targetName in _targets:
        target = getTarget(targetName)
        for t in target.uses:
            result = first_generic_target(t)
            if result is not None:
                return result
        return None

    genericTarget = getGenericTargetAndArg(targetName)
    if genericTarget and genericTarget["name"] + "-%" in _targets:
        return genericTarget

    return None


def resolve_generic_targets(name):
    genericTarget = first_generic_target(name)

    if genericTarget is not None:
        # We have an arg! Replace all our targets which name as -% with this arg
        for targetName in _targets.keys():
            target = _targets[targetName]
            if target.isGeneric():
                target.arg = genericTarget["arg"]
# -------------------------------------------------------------------------------


process_arguments()

if '--config' in _switches or '--configure' in _switches or '--conf' in _switches:
    open_editor(_use_conf.targetsJsonFilename())
    sys.exit(1)

read_default_json()

if not read_targets_json():
    print("Error loading json")
    sys.exit(1)

if len(sys.argv) == 1:
    print(currentTargetsStr())
    sys.exit(-1)

_targetName = sys.argv[1]

if "%" in _targetName:
    print("Pass an actual replacement to %")
    sys.exit(-1)


if '--edit' in _switches:
    filename = filenameForTarget(Target(_targetName))
    print("Opening editor for " + filename)
    if not open_editor(filename):
        print("Error opening editor")
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

    print(result.strip())
    sys.exit(0)

if _ask_for_ssh_keys:
    ask_for_ssh_keys()

resolve_generic_targets(_targetName)
t = getTarget(_targetName)

if t.hidden:
    print("Target is hidden!")
    sys.exit(0)

_print_env_to_file = '--print-to-file' in _switches
_print_env_only = '--print' in _switches or _print_env_to_file
if _print_env_only:
    _silent = True

if is_sourced(t):
    sys.exit(0)

if '--keep' not in _switches and not t.name.startswith('add-'):
    if not reset_env():  # source default.json
        sys.exit(1)

if _print_env_only:
    print_target(t)
    sys.exit(0)

# The actual stuff
result = run_shell_for_target(t)

if not result:
    sys.exit(1)
