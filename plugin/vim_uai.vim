if exists('g:loaded_vim_uai')
  finish
endif
let g:loaded_vim_uai = 1

command! -range -nargs=* VimUAI call vim_uai#open(<line1>, <line2>, <q-args>)
command! VimUAICancel call vim_uai#cancel()

nnoremap <silent> <Plug>(vim-uai) :<C-U>call vim_uai#open(line('.'), line('.'))<CR>
xnoremap <silent><expr> <Plug>(vim-uai) printf(":\<C-U>call vim_uai#visual(%d, %d)\<CR>", line('.'), col('.'))
inoremap <silent> <Plug>(vim-uai) <C-G>u<C-\><C-O>:call vim_uai#open(line('.'), line('.'))<CR>

if !get(g:, 'vim_uai_no_mappings', 0)
  for s:mode in ['n', 'x', 'i']
    if empty(maparg('<leader>ai', s:mode)) && !hasmapto('<Plug>(vim-uai)', s:mode)
      execute s:mode . 'map <silent> <leader>ai <Plug>(vim-uai)'
    endif
  endfor
  unlet s:mode
endif
