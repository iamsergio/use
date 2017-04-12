# Use

Use is a cross-platform application to manage your terminal's environment.
You can use it, for example, for easily changing which Qt and which compiler you have in your PATH.  
Particularly useful on Windows, where the console is a pain to work with.

Example:
```bash
$ use qt-5.2
Running /data/use_scripts/qt-5.2.source ...
$ which qmake  
/home/me/qt5.2/bin/qmake  
$ use qt-4.8  
Running /data/use_scripts/qt.4.8.source ...
$ which qmake  
/home/me/qt/4.8/bin/qmake  
```

The way it works is that you write the shell scripts (.source on Linux/macOS, .bat on Windows) which
setup the env variables you need for your targets, then just add your new target to the configuration file *use.json*.

When you run the command `use foo`, it will search for a file named `$USE_TARGETS_FOLDER/foo.source` (or foo.bat on Windows) and execute it, so you get the new set of env variables.

In *use.json* you can specify that target depends on other targets:

```json
    {
        "name" : "customer-project-A",
        "uses" : ["ccache", "gcc4.8"],
        "cwd"  : "/home/me/customerA",
    }

```

With the config above, if you run the command `use customer-project-A` it will, behind the scenes, call
ccache.source, gcc4.8.source and finally customer-project-A.source and cd into /home/me/customerA.

You can run `use` (without parameters), to know the currently sourced targets:
```bash
$ use
 core ccache clazy clazy-dev
```

and `use -h` for a list of available targets.

# Instructions

In your `.bash_profile` (or equivalent), `export USE_CONFIG_FILE`, pointing to your *use.json* file,
`export USE_TARGETS_FOLDER`, which should hold the folder containing the *.source/.bat* scripts.

Optionally, also set `USE_EDITOR`, so you can edit *use.json* with `use --conf`, or edit a script with `use foo --edit`

See `example/use.json` for a sample configuration.




Have fun using!
