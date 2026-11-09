function! Reset(lines) abort
  call vim_uai#cancel()
  enew!
  setlocal filetype=python
  call setline(1, a:lines)
  " Start with a clean undo history for each fixture.
  let &l:undolevels = &l:undolevels
endfunction

function! PopupText() abort
  if empty(popup_list())
    return []
  endif
  return getbufline(winbufnr(popup_list()[0]), 1, '$')
endfunction

function! WaitFor(title) abort
  let l:start = reltime()
  while reltimefloat(reltime(l:start)) < 5
    if !empty(popup_list()) && popup_getoptions(popup_list()[0]).title =~# a:title
      return
    endif
    sleep 10m
  endwhile
  call assert_report('Timed out waiting for ' . a:title . ': ' . string(PopupText()))
endfunction
