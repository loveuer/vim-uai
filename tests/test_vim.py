import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

from support import FakeAPI


ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("vim"), "Vim is required")
class VimTests(unittest.TestCase):
    def run_vim(self, script, api, provider="openai"):
        with tempfile.TemporaryDirectory(prefix="vim-uai-test-") as directory:
            path = pathlib.Path(directory)
            prelude = "\n".join([
                "set nocompatible encoding=utf-8 nomore",
                "set runtimepath^=" + str(ROOT).replace(" ", "\\ "),
                "runtime plugin/vim_uai.vim",
                "let g:vim_uai_api_base = " + json.dumps(api.base),
                "let g:vim_uai_provider = " + json.dumps(provider),
                "let g:vim_uai_model = 'test-model'",
                "let g:vim_uai_api_key = 'test-secret'",
                "let g:vim_uai_python = " + json.dumps(sys.executable),
                "let g:vim_uai_context_lines = 1",
                "let g:test_directory = " + json.dumps(str(path)),
                "source " + str(ROOT / "tests" / "helpers.vim").replace(" ", "\\ "),
            ])
            finish = "\n".join([
                "call writefile(v:errors, " + json.dumps(str(path / "errors")) + ")",
                "if !empty(v:errors) | cquit | endif",
                "qa!",
            ])
            (path / "test.vim").write_text(prelude + "\n" + script + "\n" + finish)
            # Keep stdin open while Vim waits in Insert mode for job/timer events.
            with subprocess.Popen(["vim", "-Nu", "NONE", "-i", "NONE", "-n", "-es",
                                   "-V1" + str(path / "log"), "-S", str(path / "test.vim")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) as process:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    self.fail("Vim timed out:\n" + (path / "log").read_text())
                stdout, stderr = process.communicate()
            errors = (path / "errors").read_text() if (path / "errors").exists() else ""
            self.assertTrue((path / "errors").exists(), "Vim exited before completing the script:\n"
                            + stdout + stderr + (path / "log").read_text())
            self.assertEqual(process.returncode, 0, errors + stdout + stderr
                             + (path / "log").read_text())

    def test_normal_mapping_preview_apply_undo_both_protocols(self):
        for provider in ("openai", "anthropic"):
            with self.subTest(provider=provider), FakeAPI() as api:
                self.run_vim(r'''
call Reset(['def answer():', '    # TODO', '# end'])
call feedkeys("2G\\ai实现 TODO\<CR>", 'xt')
call WaitFor('Enter: apply')
call assert_equal(['def answer():', '    # TODO', '# end'], getline(1, '$'))
call assert_equal(['    value = 42', '    return value'], PopupText())
call feedkeys("\<CR>", 'xt')
call assert_equal([], popup_list())
call assert_equal(['def answer():', '    value = 42', '    return value', '# end'], getline(1, '$'))
undo
call assert_equal(['def answer():', '    # TODO', '# end'], getline(1, '$'))
''', api, provider)
                edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
                self.assertEqual(edit["instruction"], "实现 TODO")
                self.assertEqual(edit["selection"]["start_line"], 2)
                self.assertEqual(edit["context_before"], ["def answer():"])
                self.assertEqual(edit["context_after"], ["# end"])
                self.assertEqual(edit["file_content"], "def answer():\n    # TODO\n# end\n")
                self.assertEqual(edit["file"], "")
                self.assertEqual(edit["filepath"], "")
                self.assertEqual(edit["cursor"]["line"], 2)

    def test_visual_range_shrinks_and_undo(self):
        with FakeAPI() as api:
            api.text = "replacement"
            self.run_vim(r'''
call Reset(['before', 'first', 'second', 'third', 'after'])
call feedkeys("2GV4G\\ai合并选区\<CR>", 'xt')
call WaitFor('Enter: apply')
call feedkeys("\<CR>", 'xt')
call assert_equal(['before', 'replacement', 'after'], getline(1, '$'))
undo
call assert_equal(['before', 'first', 'second', 'third', 'after'], getline(1, '$'))
''', api)
            edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
            self.assertEqual(edit["selection"]["text"], "first\nsecond\nthird")
            self.assertEqual(edit["selection"]["start_line"], 2)
            self.assertEqual(edit["selection"]["end_line"], 4)
            self.assertEqual(edit["cursor"]["line"], 4)

    def test_editor_context_includes_full_unsaved_buffer_both_protocols(self):
        for provider in ("openai", "anthropic"):
            with self.subTest(provider=provider), FakeAPI() as api:
                self.run_vim(r'''
let directory = g:test_directory . '/workdir 中文'
call mkdir(directory, 'p')
let filename = directory . '/working 文件.py'
call writefile(['# disk version', '    # 实现 TODO', '# disk tail'], filename)
execute 'lcd ' . fnameescape(directory)
execute 'edit ' . fnameescape(filename)
setlocal filetype=python
call setline(1, '# unsaved version')
call append('$', repeat(['# distant context'], 80))
setlocal noendofline
call cursor(2, 10)
VimUAI implement
" Changing directories during the popup must not change the captured source location.
execute 'lcd ' . fnameescape(g:test_directory)
call feedkeys("\<CR>", 'xt')
call WaitFor('Enter: apply')
VimUAICancel
''', api, provider)
                edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
                self.assertEqual(pathlib.Path(edit["workdir"]).name, "workdir 中文")
                self.assertEqual(pathlib.Path(edit["filepath"]).resolve(),
                                 (pathlib.Path(edit["workdir"]) / "working 文件.py").resolve())
                self.assertEqual(edit["file"], "working 文件.py")
                self.assertEqual(edit["filetype"], "python")
                expected_lines = ["# unsaved version", "    # 实现 TODO", "# disk tail"] + ["# distant context"] * 80
                self.assertEqual(edit["file_content"], "\n".join(expected_lines))
                self.assertEqual(edit["file_line_count"], 83)
                self.assertTrue(edit["file_modified"])
                self.assertEqual(edit["cursor"], {"line": 2, "column": 8, "byte_column": 10, "text": "    # 实现 TODO"})
                self.assertEqual(edit["selection"], {"start_line": 2, "end_line": 2, "text": "    # 实现 TODO"})
                self.assertEqual(edit["context_before"], ["# unsaved version"])
                self.assertEqual(edit["context_after"], ["# disk tail"])
                timestamp = datetime.strptime(edit["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
                self.assertLess(abs((datetime.now().astimezone() - timestamp).total_seconds()), 10)
                self.assertTrue(edit["timezone"])

    def test_full_buffer_can_be_disabled_while_preserving_target_context(self):
        with FakeAPI() as api:
            self.run_vim(r'''
call Reset(['before', 'TODO', 'after', 'distant private context'])
let g:vim_uai_send_full_buffer = 0
call cursor(2, 1)
VimUAI implement
call feedkeys("\<CR>", 'xt')
call WaitFor('Enter: apply')
VimUAICancel
''', api)
            edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
            self.assertNotIn("file_content", edit)
            self.assertNotIn("distant private context", json.dumps(edit))
            self.assertEqual(edit["selection"]["text"], "TODO")
            self.assertEqual(edit["cursor"]["line"], 2)
            self.assertEqual(edit["context_before"], ["before"])
            self.assertEqual(edit["context_after"], ["after"])

    def test_project_context_reaches_both_protocols(self):
        for provider in ("openai", "anthropic"):
            with self.subTest(provider=provider), FakeAPI() as api:
                self.run_vim(r'''
let root = g:test_directory . '/project 中文'
call mkdir(root . '/src', 'p')
call writefile(['gitdir: elsewhere'], root . '/.git')
call writefile(['Follow project conventions'], root . '/AGENTS.md')
call writefile(['Follow source conventions'], root . '/src/AGENTS.md')
call writefile(['module example/project', '', 'go 1.23'], root . '/go.mod')
call writefile(['Project overview'], root . '/README.md')
call writefile(['package main', '// TODO'], root . '/src/main.go')
call writefile(['OTHER SOURCE CONTENT NOT REQUESTED'], root . '/src/other.go')
execute 'lcd ' . fnameescape(root . '/src')
execute 'edit ' . fnameescape(root . '/src/main.go')
setlocal filetype=go
call setline(1, 'package main // unsaved')
call cursor(2, 1)
VimUAI implement
execute 'lcd ' . fnameescape(g:test_directory)
call feedkeys("\<CR>", 'xt')
call WaitFor('Enter: apply')
VimUAICancel
''', api, provider)
                edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
                project = edit["project"]
                self.assertEqual(pathlib.Path(project["root"]).name, "project 中文")
                self.assertEqual(pathlib.Path(edit["workdir"]).resolve(), pathlib.Path(project["root"]) / "src")
                self.assertEqual(project["root_source"], ".git")
                self.assertEqual(project["current_file"], "src/main.go")
                self.assertIn("src/main.go", project["tree"])
                self.assertIn("src/other.go", project["tree"])
                files = {file["path"]: file["content"] for file in project["files"]}
                self.assertEqual(files["AGENTS.md"], "Follow project conventions\n")
                self.assertEqual(files["src/AGENTS.md"], "Follow source conventions\n")
                self.assertEqual(files["go.mod"], "module example/project\n\ngo 1.23\n")
                self.assertEqual(files["README.md"], "Project overview\n")
                self.assertIn("// unsaved", edit["file_content"])
                self.assertNotIn("OTHER SOURCE CONTENT NOT REQUESTED", json.dumps(edit))

    def test_project_context_can_be_disabled(self):
        with FakeAPI() as api:
            self.run_vim(r'''
call Reset(['TODO'])
let g:vim_uai_project_context = 0
VimUAI implement
call feedkeys("\<CR>", 'xt')
call WaitFor('Enter: apply')
VimUAICancel
''', api)
            edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
            self.assertNotIn("project", edit)
            self.assertEqual(edit["file_content"], "TODO\n")

    def test_insert_mapping_keeps_insert_mode_and_separate_undo(self):
        with FakeAPI() as api:
            self.run_vim(r'''
call Reset(['def answer():', '    # TODO', '# end'])
let g:applied = 0
function! ApplyFromInsert(timer) abort
  if !empty(popup_list()) && popup_getoptions(popup_list()[0]).title =~# 'Enter: apply'
    call assert_match('^i', mode())
    let g:applied = 1
    call timer_stop(a:timer)
    call feedkeys("\<CR>\<Esc>", 't')
  endif
endfunction
function! InsertTimeout(timer) abort
  call vim_uai#cancel()
  call feedkeys("\<Esc>", 't')
endfunction
let g:timeout = timer_start(6000, function('InsertTimeout'))
let g:poll = timer_start(10, function('ApplyFromInsert'), {'repeat': -1})
call feedkeys("2GA!\\ai实现 TODO\<CR>", 'xt!')
call timer_stop(g:timeout)
call timer_stop(g:poll)
call assert_equal(1, g:applied)
call assert_equal([], popup_list())
call assert_equal(['def answer():', '    value = 42', '    return value', '# end'], getline(1, '$'))
undo
call assert_equal(['def answer():', '    # TODO!', '# end'], getline(1, '$'))
undo
call assert_equal(['def answer():', '    # TODO', '# end'], getline(1, '$'))
''', api)
            edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
            self.assertEqual(edit["selection"]["text"], "    # TODO!")

    def test_input_unicode_editing_multiline_and_discard(self):
        with FakeAPI() as api:
            self.run_vim(r'''
call Reset(['TODO'])
VimUAI
call feedkeys("实现错\<BS>对\<Left>好\<Right>\<C-J>第二行\<Home>\<Del>第\<End>\<CR>", 'xt')
call WaitFor('Enter: apply')
call feedkeys("\<Esc>", 'xt')
call assert_equal(['TODO'], getline(1, '$'))
call assert_equal([], popup_list())
''', api)
            edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
            self.assertEqual(edit["instruction"], "实现好对\n第二行")

    def test_changed_buffer_does_not_apply(self):
        with FakeAPI() as api:
            self.run_vim(r'''
call Reset(['TODO'])
VimUAI implement
call feedkeys("\<CR>", 'xt')
call WaitFor('Enter: apply')
call setline(1, 'a newer edit')
call feedkeys("\<CR>", 'xt')
call WaitFor('error')
call assert_match('source buffer changed', join(PopupText()))
call assert_equal(['a newer edit'], getline(1, '$'))
VimUAICancel
''', api)

    def test_long_prompt_keeps_input_position_visible(self):
        with FakeAPI() as api:
            self.run_vim(r'''
set columns=40 lines=16
call Reset(['TODO'])
VimUAI
call feedkeys(repeat('请实现', 80), 'xt')
redraw
let pos = popup_getpos(popup_list()[0])
" In silent Ex mode lastline is not redrawn; all displayed lines fit the width.
let visible = getbufline(winbufnr(popup_list()[0]), pos.firstline, pos.firstline + pos.core_height - 1)
call assert_match('│', join(visible))
call feedkeys("\<CR>", 'xt')
call WaitFor('Enter: apply')
VimUAICancel
''', api)
            edit = json.loads(api.requests[0]["body"]["messages"][-1]["content"])
            self.assertEqual(edit["instruction"], "请实现" * 80)

    def test_cancel_inflight_and_open_again(self):
        with FakeAPI() as api:
            api.delay = 0.15
            self.run_vim(r'''
call Reset(['TODO'])
VimUAI old request
call feedkeys("\<CR>", 'xt')
sleep 50m
call feedkeys("\<Esc>", 'xt')
call assert_equal([], popup_list())
VimUAI new request
sleep 200m
call assert_match('Prompt:', join(PopupText()))
call assert_match('new request', join(PopupText()))
call assert_equal(['TODO'], getline(1, '$'))
VimUAICancel
''', api)

    def test_api_error_does_not_change_buffer(self):
        with FakeAPI() as api:
            api.status = 401
            api.response = {"error": {"message": "Invalid credentials"}}
            self.run_vim(r'''
call Reset(['TODO'])
VimUAI implement
call feedkeys("\<CR>", 'xt')
call WaitFor('error')
call assert_match('HTTP 401', join(PopupText()))
call assert_equal(['TODO'], getline(1, '$'))
VimUAICancel
''', api)


if __name__ == "__main__":
    unittest.main()
