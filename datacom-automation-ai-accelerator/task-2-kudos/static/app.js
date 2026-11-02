// Kudos dashboard. All user content is inserted with textContent (AC-2.3).
const state = { userId: null, isAdmin: false }

const $ = (id) => document.getElementById(id)

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': String(state.userId),
      ...(options.headers || {}),
    },
  })
  if (res.status === 204) return null
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`)
  return body
}

function timeAgo(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  const steps = [[60, 'second'], [60, 'minute'], [24, 'hour'], [7, 'day'], [Infinity, 'week']]
  let value = seconds
  for (const [size, unit] of steps) {
    if (value < size) {
      const n = Math.floor(value)
      return n <= 1 && unit === 'second' ? 'just now' : `${n} ${unit}${n === 1 ? '' : 's'} ago`
    }
    value /= size
  }
  return ''
}

function renderItem(k, { admin = false } = {}) {
  const node = $('kudos-item').content.firstElementChild.cloneNode(true)
  node.querySelector('.from').textContent = k.sender.name
  node.querySelector('.to').textContent = k.recipient.name
  const time = node.querySelector('.when')
  time.dateTime = k.created_at
  time.textContent = timeAgo(k.created_at)
  node.querySelector('.msg').textContent = k.message

  if (admin) {
    const mod = node.querySelector('.mod')
    if (!k.is_visible) {
      node.classList.add('is-hidden')
      const info = document.createElement('span')
      info.textContent = `Hidden by ${k.moderation.by}${k.moderation.reason ? `: "${k.moderation.reason}"` : ''}`
      mod.append(info)
    }
    const toggle = document.createElement('button')
    toggle.className = 'secondary'
    toggle.textContent = k.is_visible ? 'Hide' : 'Restore'
    toggle.onclick = async () => {
      const reason = k.is_visible ? prompt('Reason for hiding (optional):') ?? null : null
      if (k.is_visible && reason === null) return
      await api(`/api/admin/kudos/${k.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_visible: !k.is_visible, reason }),
      })
      refresh()
    }
    const del = document.createElement('button')
    del.className = 'danger'
    del.textContent = 'Delete'
    del.onclick = async () => {
      if (!confirm('Permanently delete this kudos?')) return
      await api(`/api/admin/kudos/${k.id}`, { method: 'DELETE' })
      refresh()
    }
    mod.append(toggle, del)
  }
  return node
}

function renderList(el, items, opts) {
  el.replaceChildren(...items.map((k) => renderItem(k, opts)))
  if (!items.length) {
    const li = document.createElement('li')
    li.className = 'empty'
    li.textContent = 'No kudos yet. Be the first!'
    el.append(li)
  }
}

async function refresh() {
  const [me, colleagues, feed] = await Promise.all([
    api('/api/me'), api('/api/users'), api('/api/kudos'),
  ])
  state.isAdmin = me.is_admin

  const recipient = $('recipient')
  const selected = recipient.value
  recipient.replaceChildren(new Option('Choose a colleague…', ''))
  colleagues.forEach((u) => recipient.append(new Option(u.name, u.id)))
  recipient.value = colleagues.some((u) => String(u.id) === selected) ? selected : ''

  renderList($('feed'), feed)

  $('admin-panel').hidden = !state.isAdmin
  if (state.isAdmin) renderList($('admin-list'), await api('/api/admin/kudos'), { admin: true })
}

function setStatus(text, kind) {
  const el = $('form-status')
  el.textContent = text
  el.className = `status ${kind || ''}`
}

$('message').addEventListener('input', (e) => {
  $('counter').textContent = `${e.target.value.length} / 280`
})

$('kudos-form').addEventListener('submit', async (e) => {
  e.preventDefault()
  try {
    await api('/api/kudos', {
      method: 'POST',
      body: JSON.stringify({
        recipient_id: Number($('recipient').value) || null,
        message: $('message').value,
      }),
    })
    $('message').value = ''
    $('counter').textContent = '0 / 280'
    setStatus('Kudos sent! 🎉', 'ok')
    refresh()
  } catch (err) {
    setStatus(err.message, 'error')
  }
})

async function init() {
  const users = await fetch('/api/users/all').then((r) => r.json())
  const sw = $('user-switch')
  users.forEach((u) => sw.append(new Option(`${u.name}${u.is_admin ? ' (admin)' : ''}`, u.id)))
  state.userId = users[0]?.id
  sw.onchange = () => { state.userId = Number(sw.value); setStatus(''); refresh() }
  refresh()
}

init()
