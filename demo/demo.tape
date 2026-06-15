# VHS tape for purejq's README demo.
# Regenerate from the repo root with: vhs demo/demo.tape
Output demo/purejq.gif

Set Shell bash
Set FontSize 20
Set Width 1100
Set Height 760
Set Padding 22
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set PlaybackSpeed 1.0

# Put the project's venv on PATH so `purejq`/`python3` resolve, then clear.
Hide
Type "export PATH=$PWD/.venv/bin:$PATH; clear" Enter
Type "cd demo" Enter
Type "clear" Enter
Show

Sleep 800ms
Type "# jq, as a pure Python library.  pip install purejq" Sleep 600ms Enter
Sleep 1.2s

# 1. familiar jq on the command line
Type "purejq -r '.[] | select(.active) | .name' people.json" Sleep 500ms Enter
Sleep 2s

# 2. a real jq pipeline: commits per team
Type "purejq -c 'group_by(.team) | map({team: .[0].team, commits: map(.commits) | add})' people.json" Sleep 500ms Enter
Sleep 2.6s

# 3. the same engine, called from Python on your own dicts
Type `python3 -c "import purejq, json; d=json.load(open('people.json')); print(purejq.first('max_by(.commits).name', d))"` Sleep 500ms Enter
Sleep 2.2s

Type "# same jq. no binary, no C extension. runs anywhere Python runs." Sleep 600ms Enter
Sleep 2.5s
