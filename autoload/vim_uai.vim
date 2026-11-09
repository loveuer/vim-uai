let s:worker = expand('<sfile>:p:h:h') . '/python/vim_uai_request.py'
let s:state = {}
let s:sequence = 0

function! s:message(text) abort
  echohl WarningMsg
  echomsg '[vim-uai] ' . a:text
  echohl None
endfunction

function! s:active(token) abort
  return !empty(s:state) && s:state.token == a:token
endfunction

function! s:closed(id, result) abort
  if empty(s:state) || s:state.popup != a:id
    return
  endif
  let l:job = get(s:state, 'job', v:null)
  let s:state = {}
  if type(l:job) == v:t_job && job_status(l:job) ==# 'run'
    call job_stop(l:job)
  endif
endfunction

function! vim_uai#cancel() abort
  if !empty(s:state)
    call popup_close(s:state.popup)
  endif
endfunction

function! s:source_cursor(lnum, column) abort
  let l:text = getline(a:lnum)
  return {
        \ 'line': a:lnum, 'column': strchars(strpart(l:text, 0, a:column - 1)) + 1,
        \ 'byte_column': a:column, 'text': l:text,
        \ }
endfunction

function! vim_uai#visual(...) abort
  " Entering : from Visual moves the cursor; the mapping captures it first.
  let l:cursor = a:0 == 2 ? s:source_cursor(a:1, a:2) : s:source_cursor(line('.'), col('.'))
  call vim_uai#open(line("'<"), line("'>"), '', l:cursor)
endfunction

function! vim_uai#open(first, last, ...) abort
  if !has('popupwin') || !has('job') || !exists('*json_encode')
    call s:message('Requires Vim 8.2+ with +popupwin, +job and +channel.')
    return
  endif
  if !&modifiable || &readonly
    call s:message('The current buffer is not writable.')
    return
  endif
  if !empty(s:state)
    call s:message('A popup is already open. Close it with Esc first.')
    return
  endif
  let l:first = min([a:first, a:last])
  let l:last = max([a:first, a:last])
  if l:first < 1 || l:last > line('$')
    call s:message('Invalid line range.')
    return
  endif
  let s:sequence += 1
  let s:state = {
        \ 'token': s:sequence, 'buffer': bufnr('%'), 'tick': b:changedtick,
        \ 'first': l:first, 'last': l:last, 'filetype': &filetype,
        \ 'filename': expand('%:t'), 'selection': getline(l:first, l:last),
        \ 'filepath': expand('%:p'), 'workdir': getcwd(),
        \ 'project_root': get(b:, 'vim_uai_project_root', get(g:, 'vim_uai_project_root', '')),
        \ 'source_cursor': a:0 > 1 ? a:2 : s:source_cursor(line('.'), col('.')),
        \ 'input': a:0 ? a:1 : '', 'cursor': 0, 'mode': 'prompt',
        \ 'output': '', 'stderr': '', 'popup': 0,
        \ }
  let s:state.cursor = strchars(s:state.input)
  let l:width = max([16, min([88, &columns - 6])])
  let s:state.popup = popup_create([''], {
        \ 'pos': 'center', 'minwidth': l:width, 'maxwidth': l:width,
        \ 'maxheight': max([3, min([24, &lines - 6])]),
        \ 'border': [1, 1, 1, 1], 'padding': [0, 1, 0, 1],
        \ 'mapping': 0, 'filter': function('s:filter'),
        \ 'callback': function('s:closed'), 'wrap': 1, 'scrollbar': 1,
        \ 'highlight': 'Normal', 'borderhighlight': ['Title'],
        \ 'title': printf(' Vim UAI · lines %d–%d ', l:first, l:last),
        \ })
  call s:render_prompt()
endfunction

function! s:render_prompt() abort
  let l:preview = s:state.selection[:3]
  if len(s:state.selection) > 4
    call add(l:preview, printf('… (%d lines selected)', len(s:state.selection)))
  endif
  let l:width = max([1, popup_getpos(s:state.popup).core_width - 1])
  let l:header = s:wrap(join(
        \ ['Enter: send   Ctrl-J: newline   Esc: cancel', '', 'Selected code:']
        \ + l:preview + ['', 'Prompt:'], "\n"), l:width)
  let l:before = strcharpart(s:state.input, 0, s:state.cursor) . '│'
  let l:input = l:before . strcharpart(s:state.input, s:state.cursor)
  call popup_settext(s:state.popup, l:header + s:wrap(l:input, l:width))
  " Wrap into buffer lines so even a long single-line prompt can be scrolled.
  let l:line = len(l:header) + len(s:wrap(l:before, l:width))
  let l:height = popup_getpos(s:state.popup).core_height
  call popup_setoptions(s:state.popup, {'firstline': max([1, l:line - l:height + 1])})
endfunction

function! s:wrap(text, width) abort
  let l:result = []
  for l:line in split(a:text, "\n", 1)
    let l:chunk = ''
    let l:cells = 0
    for l:char in split(l:line, '\zs')
      let l:size = strdisplaywidth(l:char, l:cells)
      if l:cells + l:size > a:width && !empty(l:chunk)
        call add(l:result, l:chunk)
        let l:chunk = ''
        let l:cells = 0
        let l:size = strdisplaywidth(l:char)
      endif
      let l:chunk .= l:char
      let l:cells += l:size
    endfor
    call add(l:result, l:chunk)
  endfor
  return l:result
endfunction

function! s:error(text) abort
  let s:state.mode = 'error'
  call popup_setoptions(s:state.popup, {'title': ' Vim UAI · error ', 'firstline': 1})
  call popup_settext(s:state.popup, [a:text, '', 'Esc / Enter: close'])
endfunction

function! s:unchanged() abort
  return bufloaded(s:state.buffer)
        \ && bufnr('%') == s:state.buffer
        \ && getbufvar(s:state.buffer, 'changedtick') == s:state.tick
        \ && &modifiable && !&readonly
endfunction

function! s:submit() abort
  if s:state.input !~# '\S'
    return
  endif
  if !s:unchanged()
    call s:error('The source buffer changed. Close this popup and try again.')
    return
  endif
  let l:python = get(g:, 'vim_uai_python', 'python3')
  if !executable(l:python)
    call s:error('Python 3 was not found. Set g:vim_uai_python to its executable.')
    return
  endif
  let l:provider = get(g:, 'vim_uai_provider', 'openai')
  let l:anthropic = l:provider ==# 'anthropic'
  let l:context = max([0, get(g:, 'vim_uai_context_lines', 40)])
  let l:now = localtime()
  let l:request = {
        \ 'provider': l:provider,
        \ 'api_base': get(g:, 'vim_uai_api_base', l:anthropic
        \   ? 'https://api.anthropic.com/v1' : 'https://api.openai.com/v1'),
        \ 'api_key': get(g:, 'vim_uai_api_key', l:anthropic ? $ANTHROPIC_API_KEY : $OPENAI_API_KEY),
        \ 'model': get(g:, 'vim_uai_model', ''),
        \ 'max_tokens': get(g:, 'vim_uai_max_tokens', 4096),
        \ 'timeout': get(g:, 'vim_uai_timeout', 90),
        \ 'project_context': {
        \   'enabled': get(g:, 'vim_uai_project_context', 1),
        \   'root': s:state.project_root,
        \   'max_entries': get(g:, 'vim_uai_project_max_entries', 200),
        \   'max_depth': get(g:, 'vim_uai_project_max_depth', 3),
        \ },
        \ 'edit': {
        \   'instruction': s:state.input, 'file': s:state.filename,
        \   'timestamp': strftime('%Y-%m-%dT%H:%M:%S%z', l:now),
        \   'timezone': strftime('%Z', l:now),
        \   'workdir': s:state.workdir, 'filepath': s:state.filepath,
        \   'filetype': s:state.filetype, 'file_line_count': line('$'),
        \   'file_modified': &modified ? v:true : v:false,
        \   'cursor': s:state.source_cursor,
        \   'selection': {'start_line': s:state.first, 'end_line': s:state.last,
        \                 'text': join(s:state.selection, "\n")},
        \   'context_before': l:context && s:state.first > 1
        \     ? getline(max([1, s:state.first - l:context]), s:state.first - 1) : [],
        \   'context_after': l:context && s:state.last < line('$')
        \     ? getline(s:state.last + 1, min([line('$'), s:state.last + l:context])) : [],
        \ }}
  if get(g:, 'vim_uai_send_full_buffer', 1)
    " Use the current buffer, including unsaved edits, rather than reading disk.
    let l:request.edit.file_content = join(getline(1, '$'), "\n") . (&endofline ? "\n" : '')
  endif
  let s:state.mode = 'loading'
  call popup_settext(s:state.popup, ['Generating…', '', 'Esc: cancel'])
  let l:token = s:state.token
  try
    let s:state.job = job_start([l:python, s:worker], {
          \ 'in_mode': 'raw', 'out_mode': 'nl', 'err_mode': 'nl',
          \ 'out_cb': function('s:output', [l:token]),
          \ 'err_cb': function('s:stderr', [l:token]),
          \ 'close_cb': function('s:complete', [l:token]),
          \ })
    if job_status(s:state.job) ==# 'fail'
      call s:error('Could not start the Python request process.')
      return
    endif
    let l:channel = job_getchannel(s:state.job)
    " Configuration and secrets travel over stdin, never shell arguments/files.
    call ch_sendraw(l:channel, json_encode(l:request))
    call ch_close_in(l:channel)
  catch
    call s:error('Could not start the request: ' . v:exception)
  endtry
endfunction

function! s:output(token, channel, message) abort
  if s:active(a:token)
    let s:state.output .= a:message
  endif
endfunction

function! s:stderr(token, channel, message) abort
  if s:active(a:token)
    let s:state.stderr .= a:message . "\n"
  endif
endfunction

function! s:complete(token, channel) abort
  if !s:active(a:token)
    return
  endif
  try
    let l:result = json_decode(s:state.output)
    if has_key(l:result, 'error')
      call s:error(l:result.error)
      return
    endif
    if type(get(l:result, 'lines', 0)) != v:t_list || empty(l:result.lines)
      throw 'The API returned no replacement code.'
    endif
    let s:state.replacement = l:result.lines
    let s:state.mode = 'review'
    call popup_settext(s:state.popup, l:result.lines)
    call setbufvar(winbufnr(s:state.popup), '&filetype', s:state.filetype)
    call popup_setoptions(s:state.popup, {
          \ 'title': ' Vim UAI · Enter: apply · Esc: discard · j/k: scroll ',
          \ 'firstline': 1,
          \ })
  catch
    call s:error('Invalid worker response. Check Python and the API configuration.')
  endtry
endfunction

function! s:apply() abort
  if !s:unchanged()
    call s:error('The source buffer changed. The generated code was not applied.')
    return
  endif
  let l:lines = s:state.replacement
  let l:old_count = s:state.last - s:state.first + 1
  let l:common = min([l:old_count, len(l:lines)])
  call setline(s:state.first, l:lines[:l:common - 1])
  if len(l:lines) > l:old_count
    undojoin
    call append(s:state.last, l:lines[l:old_count:])
  elseif len(l:lines) < l:old_count
    undojoin
    call deletebufline(s:state.buffer, s:state.first + len(l:lines), s:state.last)
  endif
  call cursor(s:state.first, 1)
  call popup_close(s:state.popup)
endfunction

function! s:filter(id, key) abort
  if empty(s:state) || s:state.popup != a:id
    return 1
  endif
  if a:key ==# "\<Esc>"
    call popup_close(a:id)
    return 1
  endif
  if s:state.mode ==# 'loading'
    return 1
  endif
  if s:state.mode ==# 'error'
    if a:key ==# "\<CR>" || a:key ==# 'q'
      call popup_close(a:id)
    endif
    return 1
  endif
  if s:state.mode ==# 'review'
    if a:key ==# "\<CR>"
      call s:apply()
    elseif a:key ==# 'j' || a:key ==# "\<Down>" || a:key ==# "\<C-E>"
      call s:scroll(1)
    elseif a:key ==# 'k' || a:key ==# "\<Up>" || a:key ==# "\<C-Y>"
      call s:scroll(-1)
    elseif a:key ==# "\<C-D>" || a:key ==# "\<PageDown>"
      call s:scroll(max([1, popup_getpos(a:id).core_height / 2]))
    elseif a:key ==# "\<C-U>" || a:key ==# "\<PageUp>"
      call s:scroll(-max([1, popup_getpos(a:id).core_height / 2]))
    endif
    return 1
  endif
  let l:left = strcharpart(s:state.input, 0, s:state.cursor)
  let l:right = strcharpart(s:state.input, s:state.cursor)
  if a:key ==# "\<CR>"
    call s:submit()
    return 1
  elseif a:key ==# "\<BS>" || a:key ==# "\<C-H>" || a:key ==# "\x7f"
    let s:state.input = strcharpart(l:left, 0, max([0, s:state.cursor - 1])) . l:right
    let s:state.cursor = max([0, s:state.cursor - 1])
  elseif a:key ==# "\<kDel>" || a:key ==# "\<Del>"
    let s:state.input = l:left . strcharpart(l:right, 1)
  elseif a:key ==# "\<Left>"
    let s:state.cursor = max([0, s:state.cursor - 1])
  elseif a:key ==# "\<Right>"
    let s:state.cursor = min([strchars(s:state.input), s:state.cursor + 1])
  elseif a:key ==# "\<Home>" || a:key ==# "\<C-A>"
    let s:state.cursor -= strchars(split(l:left, "\n", 1)[-1])
  elseif a:key ==# "\<End>" || a:key ==# "\<C-E>"
    let s:state.cursor += strchars(split(l:right, "\n", 1)[0])
  elseif a:key ==# "\<C-U>"
    let l:count = strchars(split(l:left, "\n", 1)[-1])
    let s:state.input = strcharpart(l:left, 0, s:state.cursor - l:count) . l:right
    let s:state.cursor -= l:count
  elseif a:key ==# "\<C-J>"
    let s:state.input = l:left . "\n" . l:right
    let s:state.cursor += 1
  elseif a:key ==# "\<Tab>"
    let s:state.input = l:left . '  ' . l:right
    let s:state.cursor += 2
  elseif a:key !~# '[[:cntrl:]]' && strpart(a:key, 0, 1) !=# "\x80"
    let s:state.input = l:left . a:key . l:right
    let s:state.cursor += strchars(a:key)
  endif
  call s:render_prompt()
  return 1
endfunction

function! s:scroll(amount) abort
  let l:pos = popup_getpos(s:state.popup)
  let l:count = len(s:state.replacement)
  call popup_setoptions(s:state.popup, {
        \ 'firstline': max([1, min([l:count, l:pos.firstline + a:amount])]),
        \ })
endfunction
