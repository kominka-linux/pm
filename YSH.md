# YSH Best Practices

YSH is the new shell language from the [Oils](https://www.oilshell.org/) project.
It runs on the `ysh` interpreter (`#!/usr/local/bin/ysh`) and enables `ysh:all`
by default — strict mode, no word splitting, no implicit globbing.

Reference: <https://oils.pub/release/latest/doc/ysh-tour.html>

## Variables

```ysh
var name = 'hello'          # local, mutable
const MAX = 100             # local, immutable
setvar name = 'world'       # mutate an existing local
setglobal count = 0         # create/mutate module-level variable
```

Never leave variables unscoped. Use `var` inside procs, `setglobal` only when
you need cross-proc state (and document why).

## Procs vs Funcs

**Procs** run commands and have side effects.
**Funcs** are pure computation — they take typed args and return typed values.

```ysh
proc greet (name) {
  write "hello $name"
}

func double(n) {
  return (n * 2)
}
```

Use `func` when you can, `proc` when you must. If a function touches the
filesystem, runs commands, or sets globals, it's a `proc`.

Procs support default values and rest params:

```ysh
proc log (name, msg='', prefix='->') {
  write -- "$prefix $name $msg" >&2
}

proc build (pkg, ...flags) {
  make @flags $pkg
}
```

## Strings

```ysh
var s = 'single quoted — no interpolation'
var s = "double quoted — $var and $[expr] interpolation"
var s = $'escape sequences: \n \t \x1b[31m'
var s = '''
triple single — multiline, no interpolation
'''
var s = """
triple double — multiline with $interpolation
"""
```

Prefer single quotes for literals, double quotes when you need interpolation.
Use `$''` for escape sequences (colors, control chars).

String operations:

```ysh
var joined = a ++ b                     # concatenation
var upper = s => upper()
var yes = s => startsWith('prefix')
var slice = s[0:5]                      # Python-style slicing
echo ${#s}                              # length (legacy syntax, works fine)
echo ${s##*/}                           # parameter expansion — still good for path manipulation
echo ${s%.tar.*}                        # same — no need to avoid these
```

Parameter expansion (`${var##pat}`, `${var%pat}`, `${var:-default}`) still works
and is often the clearest way to do path/string surgery. Use it freely.

## Lists

```ysh
var files = ['a.txt', 'b.txt']          # typed List
var words = :| alpha bravo charlie |    # shell-style word array

call files->append('c.txt')
call files->extend(other_list)
call files->insert(0, 'first.txt')      # prepend (insert at index)
var item = files->pop()

for f in (files) {
  echo $f
}

for i, f in (files) {                   # with index
  echo "$i: $f"
}

echo @files                             # splice into command words
write -- @files                         # same — each element becomes one arg
```

`@list` is the splice operator. It turns a List into command words without
word-splitting ambiguity.

## Dicts

```ysh
var d = {name: 'kominka', version: 3}
setvar d['arch'] = 'x86_64'

for key in (d) { echo $key }
for key, val in (d) { echo "$key=$val" }

var exists = 'name' in d
```

Use dicts as sets for O(1) membership testing:

```ysh
var seen = {}
for item in (items) {
  if (item in seen) { continue }         # O(1) lookup
  setvar seen[item] = true
}
```

Prefer `=> startsWith()` / `=> endsWith()` over POSIX prefix-stripping idioms
for readability when you only need a boolean check:

```ysh
# Clear intent
if (url => startsWith('git+')) { ... }

# Equivalent but obscure
if (url !== "${url##git+}") { ... }
```

## Control Flow

```ysh
# Expressions use ()
if (x > 0) {
  echo positive
} elif (x === 0) {
  echo zero
} else {
  echo negative
}

# Commands use no parens
if test -f "$path" {
  echo exists
}

# Case with glob patterns
case (filename) {
  *.tar.gz | *.tgz { echo gzipped tarball }
  *.tar.xz | *.txz { echo xz tarball }
  (else)           { echo unknown }
}

# Case with expressions
case (n) {
  (1) { echo one }
  (2) { echo two }
}

# For with ranges
for i in (0 ..< 10) {
  echo $i
}

# While
while (true) {
  read --raw-line
  echo $_reply
}
```

## Error Handling

```ysh
# try/failed for commands
try { curl -fLo "$dest" "$url" }
if failed {
  echo "download failed with status $_status"
}

# error builtin for funcs
func divide(a, b) {
  if (b === 0) {
    error 'division by zero' (code=1)
  }
  return (a / b)
}

# || still works for simple cases
mkdir -p "$dir" || die "can't create $dir"
```

`try` captures the exit status in `_status` and the error in `_error`.
`if failed` is sugar for `if (_status !== 0)`.

## Globbing

In `ysh:all` mode, bare `$var` never globs. Use `@[glob()]` explicitly:

```ysh
for f in @[glob('src/*.ysh')] {
  echo $f
}

# Dynamic pattern
var pat = "$dir/*.tar.*"
for f in @[glob(pat)] {
  echo $f
}
```

## Command Substitution

```ysh
var out = $(date +%Y-%m-%d)            # string, trailing newline stripped
var lines = @(find . -name '*.ysh')    # split into List on newline
```

## I/O

```ysh
write -- $msg                           # write one line (replaces printf '%s\n')
write --end '' -- $msg                  # no trailing newline
write -- @items                         # one item per line

read --raw-line                         # read into $_reply (no IFS splitting)
read --raw-line (&myvar)               # read into named variable

# Redirections work as usual
write 'log msg' >&2
sort < input.txt > output.txt
```

Prefer `write` over `printf` / `echo`. It handles `--` correctly, never
interprets escape sequences, and outputs one argument per line by default.

## Blocks

```ysh
cd /tmp {
  # PWD is /tmp in here, restored after
  ls
}

# fork for background work
fork { long-running-thing }

# forkwait for subshell isolation
forkwait { setglobal x = 1 }
# x is unchanged here
```

## Style

- Name procs with hyphens: `pkg-install`, `run-hook`.  *(Exception: when
  matching an existing API or the name must be a valid identifier.)*
- Name funcs and variables with underscores: `find_version`, `repo_dir`.
- Use `###` docstrings as the first line of a proc/func body.
- Keep procs short. If a proc is > 50 lines, split it.
- Prefer `write` over `echo`/`printf` in new code.
- Use `@list` splicing instead of word splitting — that's the whole point of YSH.
- Use `var` for everything local. Never rely on dynamic scope.
- Avoid `setglobal` when you can thread state through parameters instead.
- Use `try`/`if failed` for commands that might fail, `||` for one-liners.
- Keep shell pipelines for what they're good at — streaming text through
  `grep | sort | uniq`. Don't force everything into YSH expressions.

## Gotchas

Things that work in POSIX/bash but break in YSH (`ysh:all` mode):

- **`$'\n'` is invalid.** Use `\n` (bare escape), `u'\n'` (J8 string), or
  `$[newline]` with a pre-defined variable.
- **`case (expr)` — no `$` in subject.** Write `case (myvar)`, not `case ($myvar)`.
  The parens create expression context; `$` is redundant and confusing.
- **Case arms starting with `/*` parse as eggex.** `/foo/*` looks like an eggex
  pattern `/ ... /`. Use `[/]foo*` or pre-compute into a variable.
- **No quotes inside `${...}` patterns.** `${var%"$x"*}` is invalid. Assign
  `$x` to a plain var first: `${var%$plain*}`.
- **No `$''` C-style strings.** Use J8 strings: `u'\u{1b}[1;33m'` for escape
  sequences, `b'\yff'` for raw bytes.
- **`var x = $(...) || die` fails.** `var` starts expression context where `||`
  isn't allowed. Split into `try { setvar x = $(...) }; if failed { die ... }`.
- **`while read ...; do` uses `{` not `do`.** All YSH loops use braces:
  `while read -r line { ... }`, `for x in (list) { ... }`.
- **`setvar` requires a prior `var` declaration.** Variables set by `read -r`
  aren't declared with `var`. Declare first or use `read --raw-line` + `_reply`.
- **`$@` / `set --` patterns won't work.** Use Lists: `var args = []`,
  `call args->append(x)`, `@args` to splice.
- **No `@list` spread in list literals.** `[a, @b]` fails. Use
  `var c = [a]; call c->extend(b)`.
- **Empty case arms `{ }` are errors.** Use `{ true }` as a no-op arm.
- **`$((...))` arithmetic is disabled.** Use `$[expr]` or `var n = x + 1`.
- **Word splitting is off.** `for x in $path_list` gives one item. Use
  `path_list => split(':')` and `for x in (result) { ... }`.
- **Environment variables aren't shell variables.** In `ysh:all` mode,
  `$HOME`, `$PATH`, `$PWD` etc. are **not** available as `$var`.  Access them
  via `ENV.HOME` (expression context) or `$[ENV.HOME]` (word context).
  To use them naturally, import at startup:
  `var HOME = ENV => get("HOME", "")`.
  After that, `$HOME` works everywhere.
- **`export` is gone.** Use `setglobal ENV.FOO = val` to set env vars that
  child processes can see.
- **`trap` syntax changed.** Use `trap --add INT { handler_body }` and
  `trap --remove INT`.  The old `trap handler_func SIGNAL` form is invalid.
- **`:` (colon) builtin is disabled.** Replace `: > file` with
  `true > file` to truncate/create a file.
- **No `||` / `&&` in `if` or `while` conditions (strict_errexit).**
  `if cmd1 && cmd2` and `while read || test` trigger OILS-ERR-300.
  Use nested `if` blocks, or `try { cmd }; if (_status === 0) { ... }`.
- **Pipelines can't be `if` conditions.** `if echo x | grep y` triggers
  OILS-ERR-300.  Use `try { echo x | grep y }; if ! failed { ... }`.
- **Procs can't appear on the left of `||`.**
  `my_proc || die "msg"` triggers OILS-ERR-301.  Use
  `try { my_proc }; if failed { die "msg" }`.
- **`while { } || true` makes the loop a conditional.** Wrap with
  `try { while ... { } }` instead.
- **`@(cmd)` splits on newlines, not spaces.** To split a string on spaces,
  use `s => split(" ")`.  `@(echo $s)` gives one element per line.
- **`=> split()` needs an argument.** Unlike Python, `s => split()` with no
  args is an error.  Use `s => split(/ ' '+ /)` for whitespace splitting.
- **`[] + []` doesn't concatenate lists.** Use
  `var c = []; call c->extend(other)`.
- **`_KOMINKA_LVL` and numeric env vars are strings.** `ENV => get(...)` always
  returns a string.  Use `int(s)` to convert before arithmetic.
- **Empty `$var` is still an argument.** No word splitting means `$CC $CFLAGS`
  with empty CFLAGS passes `""` as an arg — fatal for compilers.  Split flags
  into lists: `var CFLAGS = ENV => get("CFLAGS", "") => split(' ')` then
  splice: `$CC @CFLAGS -o out src.c`.  Empty list splices to nothing.
- **Bare globs don't expand.** `cp *.txt dir/` fails — use
  `cp @[glob('*.txt')] dir/`.  Inside `find -name '*.h'` is fine (string arg).
- **`for x in :| a b |` needs parens.** Write `for x in (:| a b |) { ... }`.
  Without parens, the `:|` is not recognized as a typed expression.
- **`$1`, `$2` etc. are gone.** Positional params in scripts use `ARGV`:
  `var dest = ARGV[0]` instead of `var dest = $1`.  `@ARGV` splices all args.
- **`IFS=x read` leaks.** In POSIX shell, `while IFS=/ read -r a b` scopes
  `IFS` to the `read` command.  In YSH, the assignment persists after the loop,
  corrupting later `read` calls.  Use `read --raw-line` + `=> split('/')`.
- **Backslashes in single-quoted strings (OILS-ERR-20).** `'\n'` and `'\('`
  are ambiguous.  Use `r'\('` (raw string) for literal backslashes, or
  `u'\n'` (J8/unicode string) for escape sequences.
- **`\\$(...)` in double quotes is still a command sub.** `\\` produces a
  literal `\`, then `$(cmd)` runs.  To get a literal `$(`, use a raw
  single-quoted prefix: `var s = r'\($(' ++ var ++ ')'`.
- **`setvar` can't modify global dicts/lists from inside procs.**
  `setvar d[key] = val` looks for a local `var d` and fails (OILS-ERR-10).
  Use `setglobal d[key] = val`.  Same for `call d->append(x)` — but `call`
  already works on globals because it mutates in-place without rebinding.
- **Expression `if` and command `if` can't mix.**
  `if (expr and test -f file)` is invalid — the `test` command can't appear
  inside expression-mode `(...)`.  Nest them:
  `if (expr) { if test -f file { ... } }`.
- **Backslash in glob/case patterns is an escape.**
  `*\V*` matches `*V*` (the `\` escapes `V`).  To match a literal backslash
  before `V`, double it: `*\\V*`.  In double-quoted strings, `"\\"` produces
  one `\`, so `"\\\\$var"` is needed to get two backslashes into a pattern.
- **OILS-ERR-20 only fires in expression context.** `'\\X'` as a proc/command
  argument (word context) is fine and produces two characters `\X`.  The same
  literal in `var x = '\\X'` (expression context) triggers OILS-ERR-20.
  Use `r'\\X'` (raw string) in expression context for literal backslashes.
