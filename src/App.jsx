import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Bell, CalendarDays, ChevronDown, ChevronRight, CircleDollarSign, Grid2X2,
  LogOut, MoreHorizontal, Plus, Search, Settings, Sparkles, Users,
  WalletCards, X, ArrowUpRight, ArrowDownLeft, Check, UserRound,
  LockKeyhole, AtSign, LoaderCircle, Megaphone, Link2,
  UserPlus, Crown, PencilLine, ScrollText, Undo2, LogOutIcon, Trash2,
  Copy, CheckCircle2, XCircle, Palette, ReceiptText, UploadCloud,
  MessageCircle, Send, Clock3, Vote, ListChecks, BarChart3, MapPin,
  ChartNoAxesCombined, TrendingUp, Building2, Layers3, Route, MapPinned,
  Navigation, Hotel, Utensils, ShoppingBag, LocateFixed, RefreshCw,
  ClipboardCheck, Flag
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import 'leaflet/dist/leaflet.css'
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { api, getToken, setToken } from './api'

delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({ iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png', iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png', shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png' })

const emptyDashboard = { stats: { expense: 0, income: 0, net: 0 }, pending_bills: [], pending_payments: [], transactions: [], activity_notifications: [], ai_bill_notifications: [] }

function Avatar({ initials, index = 0, large = false, color }) {
  return <span className={`avatar avatar-${color || index % 5} ${large ? 'avatar-large' : ''}`}>{initials}</span>
}

function App() {
  const [user, setUser] = useState(null)
  const [groups, setGroups] = useState([])
  const [activeGroup, setActiveGroup] = useState(null)
  const [dashboard, setDashboard] = useState(emptyDashboard)
  const [tab, setTab] = useState('overview')
  const [showCreate, setShowCreate] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const initialInviteCode = window.location.pathname.match(/^\/join\/([A-Za-z0-9]+)$/)?.[1] || ''
  const [showJoin, setShowJoin] = useState(Boolean(initialInviteCode))
  const [query, setQuery] = useState('')
  const [toast, setToast] = useState('')
  const [aiBillTarget, setAiBillTarget] = useState(null)
  const [billGroupTarget, setBillGroupTarget] = useState('')
  const [loading, setLoading] = useState(Boolean(getToken()))

  const filteredGroups = useMemo(() => groups.filter(g => g.name.includes(query) || g.type.includes(query)), [groups, query])
  const notify = useCallback((message) => { setToast(message); window.setTimeout(() => setToast(''), 2400) }, [])

  const loadData = async () => {
    const [me, groupData, dashboardData] = await Promise.all([api('/me'), api('/groups'), api('/dashboard')])
    setUser(me); setGroups(groupData); setDashboard(dashboardData)
    setActiveGroup(current => groupData.find(group => group.id === current?.id) || groupData[0] || null)
  }

  useEffect(() => {
    if (!getToken()) return
    Promise.all([api('/me'), api('/groups'), api('/dashboard')]).then(([me, groupData, dashboardData]) => {
      setUser(me); setGroups(groupData); setDashboard(dashboardData); setActiveGroup(groupData[0] || null)
    }).catch(() => setToken(null)).finally(() => setLoading(false))
  }, [])

  const handleAuth = async (mode, values) => {
    const result = await api(`/auth/${mode}`, { method: 'POST', body: JSON.stringify(values) })
    setToken(result.token); setUser(result.user); await loadData(); notify(mode === 'login' ? '欢迎回来' : '账号创建成功')
  }

  const logout = async () => {
    try { await api('/auth/logout', { method: 'POST' }) } finally {
      setToken(null); setUser(null); setGroups([]); setDashboard(emptyDashboard); setTab('overview')
    }
  }

  const createGroup = async (event) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    try {
      const group = await api('/groups', { method: 'POST', body: JSON.stringify({ name: data.get('name'), type: data.get('type'), template_key: data.get('template_key') || null }) })
      setGroups([group, ...groups]); setActiveGroup(group); setShowCreate(false); setTab('groups'); notify('群组已创建，快去邀请成员吧')
    } catch (error) { notify(error.message) }
  }

  if (loading) return <div className="loading-screen"><div className="brand-mark"><Sparkles size={20} /></div><LoaderCircle className="spin" size={22} /><span>正在载入 SyncMate</span></div>
  if (!user) return <AuthScreen onAuth={handleAuth} />

  const displayExpense = dashboard.stats.expense.toFixed(2)
  const netSummary = dashboard.stats.net >= 0 ? `净支出 ¥${dashboard.stats.net.toFixed(2)}` : `净结余 ¥${Math.abs(dashboard.stats.net).toFixed(2)}`
  // Legacy bills have no complete confirmation workflow in this version, so do
  // not advertise a clickable action that cannot be completed from the UI.
  const pendingCount = dashboard.pending_payments.length + (dashboard.activity_notifications?.length || 0) + (dashboard.ai_bill_notifications?.length || 0)
  const openAIBill = (groupId, billId) => { setAiBillTarget({ groupId, billId }); setTab('ai-bill') }
  const openBillRecords = (groupId = '') => { setBillGroupTarget(String(groupId || '')); setTab('wallet') }
  const recentTransactions = dashboard.transactions.map(item => ({
    title: item.title,
    sub: `${item.group_name || '个人'} · ${item.category}`,
    amount: `${item.direction === 'income' ? '+' : '-'} ¥${Number(item.amount).toFixed(2)}`,
    tone: item.direction === 'income' ? 'positive' : 'negative',
    icon: item.direction === 'income' ? ArrowDownLeft : ArrowUpRight,
  }))

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Sparkles size={17} /></div><span>SyncMate</span></div>
        <button className="profile-mini" onClick={() => setShowProfile(true)}><Avatar initials={user.initials} large color={user.avatar_color} /><div><strong>{user.nickname}</strong><small>@{user.username}</small></div><ChevronDown size={16} /></button>
        <nav className="side-nav">
          <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}><Grid2X2 size={18} />总览</button>
          <button className={tab === 'groups' ? 'active' : ''} onClick={() => setTab('groups')}><Users size={18} />我的群组 <span className="nav-count">{groups.length}</span></button>
          <button className={tab === 'calendar' ? 'active' : ''} onClick={() => setTab('calendar')}><CalendarDays size={18} />共享日程</button>
          <button className={tab === 'wallet' ? 'active' : ''} onClick={() => setTab('wallet')}><WalletCards size={18} />分账记录</button>
          <button className={tab === 'ai-bill' ? 'active' : ''} onClick={() => setTab('ai-bill')}><ReceiptText size={18} />AI 分账</button>
          <button className={tab === 'finance' ? 'active' : ''} onClick={() => setTab('finance')}><ChartNoAxesCombined size={18} />消费分析</button>
        </nav>
        <div className="sidebar-bottom"><button onClick={() => setShowProfile(true)}><Settings size={18} />个人设置</button><button onClick={logout}><LogOut size={18} />退出登录</button></div>
      </aside>

      <main className="main-content">
        <header className="topbar"><div><p className="eyebrow">TUESDAY, AUGUST 26</p><h1>{tab === 'groups' ? '我的群组' : tab === 'calendar' ? '共享日程' : tab === 'wallet' ? '分账记录' : tab === 'ai-bill' ? 'AI 分账' : tab === 'finance' ? '消费热力与财务分析' : `早上好，${user.nickname}`}</h1></div><div className="top-actions"><label className="search"><Search size={16} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索群组、账单..." /></label><button className="icon-btn" onClick={() => notify(`${pendingCount} 件事项待处理`)}><Bell size={18} />{pendingCount > 0 && <i />}</button><button className="avatar-button" onClick={() => setShowProfile(true)}><Avatar initials={user.initials} color={user.avatar_color} /></button></div></header>

        {tab === 'overview' && <>
          <section className="hero-grid"><div className="hero-card"><div className="hero-copy"><span className="label-chip"><Sparkles size={13} /> 本月概览</span><h2>让每一次<br /><em>一起生活</em>都更轻松</h2><p>账目清楚了，时间对上了，<br />剩下的就是享受当下。</p><button className="primary-btn" onClick={() => setShowCreate(true)}>创建一个新群组 <ArrowUpRight size={16} /></button></div><div className="orbital"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbital-core"><CircleDollarSign size={32} /></div><span className="float-tag tag-a">¥ {dashboard.stats.income.toFixed(0)} <small>本月收入</small></span><span className="float-tag tag-b">{groups.length} 个群组</span></div></div><div className="stat-card"><div className="stat-top"><span>我的总支出</span><MoreHorizontal size={18} /></div><strong>¥ {displayExpense}</strong><span className="trend">收入 ¥{dashboard.stats.income.toFixed(2)} <small>{netSummary}</small></span><div className="mini-chart"><span style={{height:'32%'}}/><span style={{height:'46%'}}/><span style={{height:'38%'}}/><span style={{height:'66%'}}/><span style={{height:'54%'}}/><span className="hot" style={{height:'82%'}}/><span style={{height:'70%'}}/></div><div className="chart-labels"><small>W1</small><small>W2</small><small>W3</small><small>W4</small></div></div></section>
          <section className="section-head"><div><h3>最近的群组</h3><p>和重要的人，一起把生活安排好</p></div><button className="text-btn" onClick={() => setTab('groups')}>查看全部 <ArrowUpRight size={15} /></button></section>
          <section className="group-grid">{filteredGroups.slice(0, 3).map((group, index) => <GroupCard key={group.id} group={group} index={index} onClick={() => { setActiveGroup(group); setTab('groups') }} />)}<button className="add-card" onClick={() => setShowCreate(true)}><span><Plus size={21} /></span><strong>创建新群组</strong><small>从一次聚餐开始</small></button></section>
          <section className="bottom-grid"><div className="panel"><div className="panel-head"><div><h3>待处理事项</h3><p>{pendingCount} 件事项需要你的确认</p></div><button className="more-link" onClick={() => setTab('wallet')}>全部</button></div>{(dashboard.ai_bill_notifications || []).map(item => <div className="todo" key={`ai-bill-${item.id}`}><div className="todo-icon purple"><ReceiptText size={17}/></div><div><strong>{item.status === 'pending' ? 'AI 分账待确认' : 'AI 分账待转账'}</strong><small>{item.group_name} · {item.title} · {money(item.total_cents)}</small></div><button title="查看分账方案" onClick={() => openAIBill(item.group_id, item.id)}><ArrowUpRight size={16}/></button></div>)}{(dashboard.activity_notifications || []).map(item => <div className="todo" key={`activity-${item.id}`}><div className="todo-icon green"><Vote size={17}/></div><div><strong>活动投票已全部完成</strong><small>{item.group_name} · {item.title}</small></div><button onClick={() => { const group=groups.find(g=>g.id===item.group_id); if(group){setActiveGroup(group);setTab('groups')} }}><ArrowUpRight size={16}/></button></div>)}{dashboard.pending_payments.map(item => <div className="todo" key={`payment-${item.id}`}><div className="todo-icon green"><CircleDollarSign size={17} /></div><div><strong>{item.status === 'pending_in' ? '待确认收款' : '待付款'}</strong><small>{item.group_name} · ¥{Number(item.amount).toFixed(2)}</small></div><button onClick={() => setTab('wallet')}><ArrowUpRight size={16} /></button></div>)}{pendingCount === 0 && <div className="empty-state"><Check size={20} />当前没有待处理事项</div>}</div><div className="panel"><div className="panel-head"><div><h3>最近动态</h3><p>你的个人收支记录</p></div><button className="more-link" onClick={() => setTab('wallet')}>全部</button></div>{recentTransactions.map((item, index) => <div className="transaction" key={`${item.title}-${index}`}><div className={`transaction-icon ${item.tone}`}><item.icon size={15} /></div><div><strong>{item.title}</strong><small>{item.sub}</small></div><b className={item.tone}>{item.amount}</b></div>)}</div></section>
        </>}

        {tab === 'groups' && <GroupsView groups={filteredGroups} activeGroup={activeGroup} setActiveGroup={setActiveGroup} onCreate={() => setShowCreate(true)} onJoin={() => setShowJoin(true)} notify={notify} refresh={loadData} user={user} onOpenBills={openBillRecords} />}
        {tab === 'calendar' && <CalendarView notify={notify} />}
        {tab === 'wallet' && <WalletView notify={notify} dashboard={dashboard} groupId={billGroupTarget} onClearGroup={() => setBillGroupTarget('')} />}
        {tab === 'ai-bill' && <AIBillView groups={groups} user={user} notify={notify} target={aiBillTarget} onDataChanged={loadData} />}
        {tab === 'finance' && <FinanceAnalytics groups={groups} notify={notify} />}
      </main>
      {toast && <div className="toast"><Check size={16} />{toast}</div>}
      {showCreate && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setShowCreate(false)}><form className="modal" onSubmit={createGroup}><button type="button" className="modal-close" onClick={() => setShowCreate(false)}><X size={18} /></button><span className="modal-kicker">NEW CIRCLE</span><h2>创建一个新群组</h2><p>选择模板可以自动填入更适合该场景的公告与主题。</p><label>群组名称<input name="name" required placeholder="例如：周末聚餐" /></label><label>群组模板<select name="template_key"><option value="">自定义</option><option value="dorm">宿舍协同</option><option value="roommate">合租生活</option><option value="trip">结伴旅行</option><option value="dinner">聚餐活动</option></select></label><label>群组类型<select name="type"><option>好友</option><option>旅行</option><option>宿舍</option><option>合租</option><option>聚餐</option></select></label><button className="primary-btn" type="submit">创建群组 <ArrowUpRight size={16} /></button></form></div>}
      {showJoin && <JoinGroupModal initialCode={initialInviteCode} onClose={() => setShowJoin(false)} onJoined={async (message) => { setShowJoin(false); window.history.replaceState({}, '', '/'); await loadData(); notify(message) }} />}
      {showProfile && <ProfileModal user={user} onClose={() => setShowProfile(false)} onSaved={(next) => { setUser(next); setShowProfile(false); notify('个人资料已保存') }} notify={notify} />}
    </div>
  )
}

function GroupCard({ group, index, onClick }) { return <button className={`group-card ${group.color}`} onClick={onClick}><div className="card-top"><span className="group-type">{group.type}</span><MoreHorizontal size={18} /></div><div className="group-art"><div className="ring" /><span className="art-symbol">{index === 0 ? '✦' : index === 1 ? '◒' : '⌂'}</span></div><div className="card-info"><div><h4>{group.name}</h4><small><Users size={13} /> {group.people} 位成员</small></div><strong>{group.amount}</strong></div><div className="card-foot"><div className="avatar-stack">{group.members.map((m, i) => <Avatar key={m} initials={m} index={i} />)}</div><span>本月总额</span></div></button> }
function GroupsView({ groups, activeGroup, setActiveGroup, onCreate, onJoin, notify, refresh, user, onOpenBills }) {
  const [detail, setDetail] = useState(null)
  const [view, setView] = useState('overview')
  const [editingMember, setEditingMember] = useState(null)
  const [busy, setBusy] = useState(false)
  const loadDetail = async () => {
    if (!activeGroup) return setDetail(null)
    try { setDetail(await api(`/groups/${activeGroup.id}`)) } catch (error) { notify(error.message) }
  }
  useEffect(() => {
    if (!activeGroup?.id) return
    let cancelled = false
    api(`/groups/${activeGroup.id}`).then(result => { if (!cancelled) setDetail(result) }).catch(error => notify(error.message))
    return () => { cancelled = true }
  }, [activeGroup?.id, notify])
  const act = async (work, success, reloadGroups = false, reloadDetail = true) => {
    setBusy(true)
    try { await work(); if (reloadGroups) await refresh(); if (reloadDetail) await loadDetail(); notify(success) }
    catch (error) { notify(error.message) }
    finally { setBusy(false) }
  }
  const roleNames = { owner: '群主', admin: '管理员', member: '普通成员' }
  const canManage = ['owner', 'admin'].includes(detail?.current_role)
  if (!activeGroup) return <div className="empty-page"><Users size={30}/><h3>还没有群组</h3><p>创建群组或使用邀请码加入。</p><div><button className="primary-btn small" onClick={onCreate}>创建群组</button><button className="secondary-btn" onClick={onJoin}>邀请码加入</button></div></div>
  return <div className="group-manager">
    <aside className="group-rail"><div className="section-head compact"><div><h3>我的群组 <span className="muted-count">{groups.length}</span></h3><p>群组生活协同中心</p></div></div><div className="rail-actions"><button onClick={onCreate}><Plus size={15}/>新建</button><button onClick={onJoin}><Link2 size={15}/>加入</button></div><div className="groups-list">{groups.map((group, index) => <button className={`group-row ${activeGroup.id === group.id ? 'selected' : ''}`} key={group.id} onClick={() => { setActiveGroup(group); setView('overview') }}><div className={`row-art ${group.color}`}>{index === 0 ? '✦' : index === 1 ? '◒' : '⌂'}</div><div className="row-main"><strong>{group.name}</strong><small>{group.type} · {group.people} 位成员</small></div><b>{group.amount}</b></button>)}</div></aside>
    <section className="group-workspace">{!detail ? <div className="detail-loading"><LoaderCircle className="spin"/>加载群组资料</div> : <>
      <div className={`group-cover ${detail.theme_color} cover-${detail.cover_style}`}><div className="cover-copy"><span className="group-type">{detail.type}</span><h2>{detail.name}</h2><p>{detail.announcement || '还没有群公告，管理员可以在设置中添加。'}</p><div className="cover-meta"><span><Users size={14}/>{detail.people} 位成员</span><span><Crown size={14}/>{roleNames[detail.current_role]}</span><span><CircleDollarSign size={14}/>{detail.amount}</span></div></div><div className="cover-symbol"><Sparkles size={28}/></div></div>
      <div className="group-tabs"><button className={view === 'overview' ? 'active' : ''} onClick={() => setView('overview')}><Grid2X2 size={15}/>概览</button><button className={view === 'chat' ? 'active' : ''} onClick={() => setView('chat')}><MessageCircle size={15}/>聊天</button><button className={view === 'activities' ? 'active' : ''} onClick={() => setView('activities')}><CalendarDays size={15}/>活动</button><button className={view === 'travel' ? 'active' : ''} onClick={() => setView('travel')}><Route size={15}/>旅行路线</button><button className={view === 'members' ? 'active' : ''} onClick={() => setView('members')}><Users size={15}/>成员</button><button className={view === 'invite' ? 'active' : ''} onClick={() => setView('invite')}><UserPlus size={15}/>邀请与审核{detail.join_requests.length > 0 && <b>{detail.join_requests.length}</b>}</button>{canManage && <button className={view === 'settings' ? 'active' : ''} onClick={() => setView('settings')}><Settings size={15}/>设置</button>}<button className={view === 'logs' ? 'active' : ''} onClick={() => setView('logs')}><ScrollText size={15}/>日志</button></div>
      {view === 'overview' && <GroupOverview detail={detail} setView={setView} notify={notify} onOpenBills={onOpenBills}/>} 
      {view === 'chat' && <ChatPanel groupId={detail.id} user={user} notify={notify}/>} 
      {view === 'activities' && <ActivitiesPanel groupId={detail.id} detail={detail} canManage={canManage} notify={notify}/>} 
      {view === 'travel' && <TravelRoutesView groupId={detail.id} detail={detail} canManage={canManage} notify={notify}/>}
      {view === 'members' && <div className="manager-panel"><div className="manager-head"><div><h3>成员与权限</h3><p>成员备注、群内昵称、角色和加入时间</p></div><span>{detail.people} 人</span></div><div className="member-table">{detail.members_detail.map(member => <div className="member-record" key={member.id}><Avatar initials={member.initials} color={member.avatar_color}/><div className="member-identity"><strong>{member.display_name}</strong><small>@{member.username}{member.member_note ? ` · ${member.member_note}` : ''}</small></div><span className={`role-chip ${member.role}`}>{member.role === 'owner' && <Crown size={12}/>} {roleNames[member.role]}</span><time>{formatDate(member.joined_at)} 加入</time>{(canManage || member.id === user.id) && <button className="table-action" onClick={() => setEditingMember(member)}><PencilLine size={15}/></button>}</div>)}</div></div>}
      {view === 'invite' && <InvitePanel detail={detail} canManage={canManage} act={act} notify={notify}/>} 
      {view === 'settings' && canManage && <GroupSettings detail={detail} act={act} refresh={refresh}/>} 
      {view === 'logs' && <div className="manager-panel"><div className="manager-head"><div><h3>操作日志</h3><p>重要变更保留记录，部分操作支持撤销</p></div></div><div className="log-list">{detail.audit_logs.map(log => <div className="log-record" key={log.id}><div className="log-icon"><ScrollText size={15}/></div><div><strong>{log.summary}</strong><small>{log.actor} · {formatDate(log.created_at)}</small></div>{Boolean(log.undoable) && !log.undone && canManage && <button disabled={busy} onClick={() => act(() => api(`/groups/${detail.id}/logs/${log.id}/undo`, {method:'POST'}), '操作已撤销', true)}><Undo2 size={14}/>撤销</button>}{Boolean(log.undone) && <span>已撤销</span>}</div>)}</div></div>}
    </>}</section>
    {editingMember && <MemberModal member={editingMember} detail={detail} currentUser={user} onClose={() => setEditingMember(null)} onSave={async payload => { await act(() => api(`/groups/${detail.id}/members/${editingMember.id}`, {method:'PATCH', body:JSON.stringify(payload)}), '成员资料已更新'); setEditingMember(null) }} onRemove={async () => { await act(() => api(`/groups/${detail.id}/members/${editingMember.id}`, {method:'DELETE'}), '成员已移除', true); setEditingMember(null) }}/>} 
  </div>
}

function travelPlaceIcon(type) {
  return type === 'hotel' ? Hotel : type === 'restaurant' ? Utensils : type === 'shopping' ? ShoppingBag : type === 'meeting' ? Users : MapPin
}

// The default OSM host is intermittently reset by the current network. The
// German OSM tile mirror serves the same data without an API key and is much
// more stable for this app's map views.
const OPEN_STREET_MAP_TILES = 'https://tile.openstreetmap.de/{z}/{x}/{y}.png'

function getMapPoint(item, latKey = 'lat', lngKey = 'lng') {
  const lat = Number(item?.[latKey])
  const lng = Number(item?.[lngKey])
  return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? [lat, lng] : null
}

function MapEffects({ center, zoom, points = [], fitBounds = true }) {
  const map = useMap()
  const pointKey = points.map(point => point.join(',')).join('|')
  const centerLat = center[0]
  const centerLng = center[1]
  const pointCount = points.length
  const firstLat = points[0]?.[0] ?? centerLat
  const firstLng = points[0]?.[1] ?? centerLng
  const bounds = useMemo(() => {
    if (!fitBounds || pointCount <= 1) return null
    const parsedPoints = pointKey.split('|').map(value => value.split(',').map(Number))
    const nextBounds = L.latLngBounds(parsedPoints)
    return nextBounds.isValid() ? nextBounds : null
  }, [fitBounds, pointCount, pointKey])

  useEffect(() => {
    const refreshSize = () => map.invalidateSize({ pan: false })
    const frame = window.requestAnimationFrame(refreshSize)
    const timer = window.setTimeout(refreshSize, 180)
    window.addEventListener('resize', refreshSize)
    let observer
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(refreshSize)
      observer.observe(map.getContainer())
    }
    return () => {
      window.cancelAnimationFrame(frame)
      window.clearTimeout(timer)
      window.removeEventListener('resize', refreshSize)
      observer?.disconnect()
    }
  }, [map])

  useEffect(() => {
    if (bounds) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13, animate: false })
      return
    }
    if (pointCount === 1) {
      map.setView([firstLat, firstLng], zoom, { animate: false })
      return
    }
    map.setView([centerLat, centerLng], zoom, { animate: false })
  }, [bounds, centerLat, centerLng, firstLat, firstLng, map, pointCount, zoom])

  return null
}

const MAP_OPTIONS = {
  zoomControl: true,
  scrollWheelZoom: true,
  doubleClickZoom: true,
  dragging: true,
  touchZoom: true,
  boxZoom: true,
  keyboard: true,
  preferCanvas: true,
  wheelDebounceTime: 40,
  wheelPxPerZoomLevel: 60,
  zoomAnimation: false,
  fadeAnimation: false,
  markerZoomAnimation: false
}

function MapTiles() {
  const [provider, setProvider] = useState('osm')
  const switched = useRef(false)
  const fallback = () => {
    if (switched.current) return
    switched.current = true
    setProvider('esri')
  }
  const isEsri = provider === 'esri'
  return <TileLayer key={provider} attribution={isEsri ? 'Tiles © Esri' : '© OpenStreetMap contributors'} url={isEsri ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}' : OPEN_STREET_MAP_TILES} updateWhenIdle updateWhenZooming={false} keepBuffer={2} maxZoom={19} eventHandlers={{tileerror:fallback}}/>
}

function TravelMap({ places = [], nodes = [] }) {
  const source = nodes.length ? nodes : places
  let mapped = source.map((place, index) => ({ place, index, point: getMapPoint({ lat: place.place_lat ?? place.lat, lng: place.place_lng ?? place.lng }) })).filter(item => item.point)
  if (!mapped.length && nodes.length) mapped = places.map((place, index) => ({ place, index, point: getMapPoint({ lat: place.place_lat ?? place.lat, lng: place.place_lng ?? place.lng }) })).filter(item => item.point)
  const points = mapped.map(item => item.point)
  const center = points[0] || [31.2304, 121.4737]
  const zoom = points.length ? 11 : 4
  return <div className="travel-map"><MapContainer {...MAP_OPTIONS} center={center} zoom={zoom} className="travel-map-canvas"><MapEffects center={center} zoom={zoom} points={points}/><MapTiles/>{points.length > 1 && <Polyline positions={points} pathOptions={{color:'#6e9568', weight:4, opacity:.8, dashArray:'7 5'}}/>}{mapped.map(({ place, index, point }) => { const name = place.place_name || place.name; return <Marker key={`${place.id || index}-${point[0]}-${point[1]}`} position={point}><Popup><strong>{index + 1}. {name}</strong><br/>{place.place_address || place.address || '未填写地址'}<br/>{place.total_distance_km != null ? `距上一节点 ${place.distance_km || 0} 公里` : ''}</Popup></Marker>})}</MapContainer>{!points.length && <div className="travel-map-empty"><MapPinned size={18}/>添加地点后将在地图上显示</div>}</div>
}

function TravelRoutesView({ groupId, _detail, canManage, notify }) {
  const [plans, setPlans] = useState([])
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [activeDayId, setActiveDayId] = useState(null)
  const [showPlaceForm, setShowPlaceForm] = useState(false)
  const [showDayForm, setShowDayForm] = useState(false)
  const [pickedPlace, setPickedPlace] = useState(null)
  const [selectedPlaces, setSelectedPlaces] = useState([])
  const [autoOptions, setAutoOptions] = useState([])
  const [meeting, setMeeting] = useState(null)
  const [checks, setChecks] = useState(null)
  const [placeSuggestions, setPlaceSuggestions] = useState({})
  const [busy, setBusy] = useState(false)

  const loadPlans = useCallback(async (preferredId = null) => {
    setLoading(true)
    try {
      const rows = await api(`/groups/${groupId}/travel-plans`)
      setPlans(rows)
      const target = preferredId || plan?.id || rows[0]?.id
      if (target) setPlan(await api(`/travel-plans/${target}`))
      else setPlan(null)
    } catch (error) { notify(error.message) } finally { setLoading(false) }
  }, [groupId, notify, plan?.id])

  useEffect(() => { loadPlans() }, [loadPlans])
  useEffect(() => {
    const day = plan?.days?.find(item => item.id === activeDayId) || plan?.days?.[0]
    setActiveDayId(day?.id || null)
    setSelectedPlaces(day?.nodes?.map(node => node.place_id) || [])
  }, [plan, activeDayId])

  const refreshPlan = async () => { if (plan?.id) { setPlan(await api(`/travel-plans/${plan.id}`)); await loadPlans(plan.id) } }
  const switchPlan = async event => { const nextId = Number(event.target.value); if (!nextId || nextId === plan?.id) return; await run(async () => setPlan(await api(`/travel-plans/${nextId}`))) }
  const run = async (work, success) => { if (busy) return; setBusy(true); try { await work(); if (success) notify(success) } catch (error) { notify(error.message) } finally { setBusy(false) } }
  const createPlan = async event => {
    event.preventDefault(); const data = new FormData(event.currentTarget)
    await run(async () => { const created = await api(`/groups/${groupId}/travel-plans`, {method:'POST', body:JSON.stringify({name:data.get('name'), destination:data.get('destination'), start_date:data.get('start_date'), end_date:data.get('end_date'), departure_city:data.get('departure_city'), default_start_point:data.get('default_start_point'), default_transport:data.get('default_transport'), estimated_people:Number(data.get('estimated_people') || 1), budget_cents:Math.round(Number(data.get('budget') || 0) * 100), notes:data.get('notes') || ''})}); setShowCreate(false); await loadPlans(created.id) }, '旅行计划创建成功，当前为草稿状态')
  }
  const addPlace = async event => {
    event.preventDefault(); const data = new FormData(event.currentTarget); const picked = pickedPlace || {}
    await run(async () => { await api(`/travel-plans/${plan.id}/places`, {method:'POST', body:JSON.stringify({type:data.get('type'), name:data.get('name') || picked.name, address:data.get('address') || picked.address || '', lat:Number(data.get('lat') || picked.lat), lng:Number(data.get('lng') || picked.lng), opening_hours:data.get('opening_hours') || '', avg_cost:data.get('avg_cost') ? Number(data.get('avg_cost')) : null, rating:data.get('rating') ? Number(data.get('rating')) : null, must_visit:data.get('must_visit') === 'on', note:data.get('note') || ''})}); setShowPlaceForm(false); setPickedPlace(null); await refreshPlan() }, '地点已加入旅行计划')
  }
  const addDay = async event => {
    event.preventDefault(); const data = new FormData(event.currentTarget)
    await run(async () => { await api(`/travel-plans/${plan.id}/days`, {method:'POST', body:JSON.stringify({travel_date:data.get('travel_date'), title:data.get('title'), start_at:data.get('start_at') || null, end_at:data.get('end_at') || null, start_place_id:data.get('start_place_id') ? Number(data.get('start_place_id')) : null, end_place_id:data.get('end_place_id') ? Number(data.get('end_place_id')) : null, transport:data.get('transport'), budget_cents:Math.round(Number(data.get('budget') || 0) * 100), notes:data.get('notes') || ''})}); setShowDayForm(false); await refreshPlan() }, '每日行程已创建')
  }
  const saveRoute = async () => {
    const day = plan?.days?.find(item => item.id === activeDayId); if (!day) return
    await run(async () => { await api(`/travel-days/${day.id}/route`, {method:'PUT', body:JSON.stringify({nodes:selectedPlaces.map(placeId => ({place_id:placeId, stay_minutes:60, transport:day.transport, confirmed:true}))})}); await refreshPlan() }, '路线顺序已保存，距离和时长已重新计算')
  }
  const autoPlan = async event => {
    event.preventDefault(); const data = new FormData(event.currentTarget)
    await run(async () => { const result = await api(`/travel-plans/${plan.id}/auto-plan`, {method:'POST', body:JSON.stringify({travel_date:data.get('travel_date') || null, max_play_minutes:Number(data.get('max_play_minutes') || 600), earliest_start:data.get('earliest_start') || '09:00', latest_end:data.get('latest_end') || '21:00', transport:data.get('transport') || plan.default_transport, prioritize:data.get('prioritize') || 'balanced'})}); setAutoOptions(result.options || []) }, '已生成多套路线方案')
  }
  const applyOption = async optionId => { await run(async () => { await api(`/travel-plans/${plan.id}/apply-plan`, {method:'POST', body:JSON.stringify({option_id:optionId})}); setAutoOptions([]); await refreshPlan() }, '路线方案已应用') }
  const shareLocation = () => { if (!navigator.geolocation) return notify('当前浏览器不支持定位，请手动提交经纬度'); navigator.geolocation.getCurrentPosition(position => run(async () => { await api(`/travel-plans/${plan.id}/location`, {method:'POST',body:JSON.stringify({lat:position.coords.latitude,lng:position.coords.longitude,address:'浏览器当前位置',participating:true})}); notify('已提交本次旅行集合位置') }), () => notify('未获得定位权限，可改用手动位置')) }
  const loadMeeting = async () => { await run(async () => setMeeting(await api(`/travel-plans/${plan.id}/meeting-recommendation`))) }
  const votePlace = async placeId => { await run(async () => { await api(`/travel-plans/${plan.id}/places/${placeId}/vote`, {method:'POST', body:JSON.stringify({suggestion:placeSuggestions[placeId] || ''})}); await refreshPlan() }, '地点投票已提交') }
  const publish = async () => { await run(async () => { const result = await api(`/travel-plans/${plan.id}/publish`, {method:'POST'}); setChecks(result.checks); await refreshPlan() }, '旅行行程已发布') }
  const check = async () => { await run(async () => setChecks(await api(`/travel-plans/${plan.id}/publish-check`))) }
  const syncCalendar = async () => { await run(async () => { const result = await api(`/travel-plans/${plan.id}/sync-calendar`, {method:'POST'}); notify(`${result.count} 天路线已同步到共享日程`); await refreshPlan() }) }
  const activeDay = plan?.days?.find(item => item.id === activeDayId) || plan?.days?.[0]
  if (loading && !plan) return <div className="manager-panel detail-loading"><LoaderCircle className="spin"/>正在加载旅行路线</div>
  if (!plan) return <div className="travel-page"><div className="travel-empty"><Route size={30}/><h3>还没有旅行计划</h3><p>从目的地、日期和预算开始，建立群组共同路线。</p>{canManage && <button className="primary-btn" onClick={() => setShowCreate(true)}><Plus size={15}/>新建旅行计划</button>}</div>{showCreate && <TravelPlanCreateModal onClose={() => setShowCreate(false)} onSubmit={createPlan} busy={busy}/>}</div>
  return <div className="travel-page">
    <div className="travel-header"><div><span className="label-chip"><Route size={13}/> TRAVEL ROUTE</span><h2>{plan.name}</h2><p>{plan.destination} · {plan.start_date} 至 {plan.end_date} · {plan.estimated_people} 人 · 状态：{plan.status === 'draft' ? '草稿' : plan.status === 'planning' ? '规划中' : plan.status === 'published' ? '已发布' : plan.status}</p></div><div className="travel-header-actions">{plans.length > 1 && <select className="travel-plan-select" value={plan.id} onChange={switchPlan}>{plans.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}{canManage && <button className="secondary-btn" onClick={() => setShowCreate(true)}><Plus size={14}/>新建计划</button>}<span className={`travel-status ${plan.status}`}>{plan.status === 'published' ? '已发布' : plan.status === 'draft' ? '草稿' : '规划中'}</span></div></div>
    <div className="travel-toolbar"><button className="secondary-btn" onClick={() => setShowPlaceForm(!showPlaceForm)} disabled={!canManage}><MapPinned size={14}/>地点管理</button><button className="secondary-btn" onClick={() => setShowDayForm(!showDayForm)} disabled={!canManage}><CalendarDays size={14}/>新增每日路线</button><button className="secondary-btn" onClick={shareLocation}><LocateFixed size={14}/>提交集合位置</button><button className="secondary-btn" onClick={loadMeeting}><Navigation size={14}/>集合点推荐</button><button className="secondary-btn" onClick={check}><ClipboardCheck size={14}/>发布前检查</button>{canManage && plan.status !== 'published' && <button className="primary-btn small" onClick={publish}><Flag size={14}/>发布最终行程</button>}{canManage && plan.status === 'published' && <button className="primary-btn small" onClick={syncCalendar}><CalendarDays size={14}/>同步共享日程</button>}</div>
    {showPlaceForm && <form key={`${pickedPlace?.lat || 'manual'}-${pickedPlace?.lng || ''}`} className="panel travel-editor-form" onSubmit={addPlace}><div className="panel-head"><div><h3>添加旅行地点</h3><p>可搜索地图、地图选点或手动填写，地点会出现在旅行地图中。</p></div><MapPinned size={18}/></div><LocationSearch onAdd={place => setPickedPlace(place)}/><div className="travel-form-grid"><label>地点类型<select name="type" defaultValue="attraction"><option value="attraction">景点</option><option value="hotel">酒店</option><option value="restaurant">餐厅</option><option value="shopping">购物</option><option value="meeting">集合点</option><option value="other">其他</option></select></label><label>地点名称<input name="name" required defaultValue={pickedPlace?.name || ''}/></label><label>地址<input name="address" defaultValue={pickedPlace?.address || ''}/></label><label>纬度<input name="lat" type="number" step="any" required defaultValue={pickedPlace?.lat || ''}/></label><label>经度<input name="lng" type="number" step="any" required defaultValue={pickedPlace?.lng || ''}/></label><label>人均消费（元）<input name="avg_cost" type="number" min="0" step="0.01"/></label><label>营业时间<input name="opening_hours" placeholder="例如 09:00-21:00"/></label><label>评分（0-5）<input name="rating" type="number" min="0" max="5" step="0.1"/></label></div><label className="travel-check-line"><input name="must_visit" type="checkbox"/>设为必去地点</label><label>地点备注<textarea name="note" rows="2" placeholder="停留建议、预约说明等"/></label><div className="travel-form-actions"><button type="button" className="secondary-btn" onClick={() => setShowPlaceForm(false)}>取消</button><button className="primary-btn small" disabled={busy}>保存地点</button></div></form>}
    {showDayForm && <form className="panel travel-editor-form" onSubmit={addDay}><div className="panel-head"><div><h3>创建每日行程</h3><p>时间精确到分钟，起点和终点用于逐段路线计算。</p></div><CalendarDays size={18}/></div><div className="travel-form-grid"><label>日期<input name="travel_date" type="date" min={plan.start_date} max={plan.end_date} required defaultValue={plan.start_date}/></label><label>行程标题<input name="title" placeholder="例如：城市经典一日游"/></label><label>出发时间<input name="start_at" type="datetime-local" required/></label><label>返回时间<input name="end_at" type="datetime-local" required/></label><label>起点<select name="start_place_id"><option value="">请选择地点</option>{plan.places.map(place => <option key={place.id} value={place.id}>{place.name}</option>)}</select></label><label>终点<select name="end_place_id"><option value="">请选择地点</option>{plan.places.map(place => <option key={place.id} value={place.id}>{place.name}</option>)}</select></label><label>交通方式<select name="transport" defaultValue={plan.default_transport}><option value="drive">驾车</option><option value="transit">公交</option><option value="walk">步行</option><option value="bike">骑行</option></select></label><label>当日预算（元）<input name="budget" type="number" min="0" step="0.01"/></label></div><label>备注<textarea name="notes" rows="2"/></label><div className="travel-form-actions"><button type="button" className="secondary-btn" onClick={() => setShowDayForm(false)}>取消</button><button className="primary-btn small" disabled={busy}>保存当天行程</button></div></form>}
    <div className="travel-overview-grid"><div className="panel travel-plan-summary"><div className="panel-head"><div><h3>旅行总览</h3><p>{plan.notes || '将地点、每日路线、预算和共享日程放在一起管理。'}</p></div><Route size={18}/></div><div className="travel-kpis"><div><span>地点</span><strong>{plan.place_count}</strong><small>{plan.must_visit_count} 个必去</small></div><div><span>每日路线</span><strong>{plan.day_count}</strong><small>{plan.days.filter(day => day.nodes.length).length} 天已排路线</small></div><div><span>预算</span><strong>¥{Number(plan.budget || 0).toFixed(2)}</strong><small>可在发布前检查</small></div><div><span>距离</span><strong>{plan.days.reduce((sum, day) => sum + Number(day.total_distance_km || 0), 0).toFixed(1)} km</strong><small>免费估算</small></div></div><TravelMap places={plan.places}/></div><div className="panel travel-place-list"><div className="panel-head"><div><h3>地点清单</h3><p>地图搜索结果和手动地点会统一保存</p></div><MapPinned size={18}/></div>{plan.places.map(place => { const Icon = travelPlaceIcon(place.type); return <div className="travel-place-row" key={place.id}><span className="travel-place-icon"><Icon size={15}/></span><div><strong>{place.name}{place.must_visit && <em>必去</em>}</strong><small>{place.address || `${place.lat}, ${place.lng}`}</small><small>{place.vote_count || 0} 人投票</small></div><input className="travel-place-suggestion" value={placeSuggestions[place.id] || ''} onChange={event => setPlaceSuggestions(rows => ({...rows, [place.id]:event.target.value}))} placeholder="地点建议"/><button className="secondary-btn travel-vote-btn" onClick={() => votePlace(place.id)} disabled={busy}>{place.my_vote ? '已投票' : '投票'}</button><b>{place.avg_cost != null ? `¥${Number(place.avg_cost).toFixed(0)}/人` : '—'}</b></div>})}{!plan.places.length && <div className="empty-state">先添加第一个景点、酒店或餐厅</div>}</div></div>
    <div className="travel-route-grid"><div className="panel travel-days-panel"><div className="panel-head"><div><h3>每日路线</h3><p>可手动调整顺序，也可以自动生成 2～3 套方案。</p></div><RefreshCw size={18}/></div>{plan.days.map(day => <button key={day.id} className={`travel-day-tab ${day.id === activeDay?.id ? 'active' : ''}`} onClick={() => { setActiveDayId(day.id); setSelectedPlaces(day.nodes.map(node => node.place_id)) }}><span>{day.travel_date.slice(5)}</span><strong>{day.title}</strong><small>{day.nodes.length} 个地点 · {day.total_distance_km} km</small></button>)}{!plan.days.length && <div className="empty-state">创建每日行程后在这里调整路线</div>}{activeDay && <div className="travel-day-editor"><div className="travel-day-editor-head"><div><strong>{activeDay.title}</strong><small>{activeDay.travel_date} · {activeDay.start_at ? `${formatDateTime(activeDay.start_at)} - ${formatDateTime(activeDay.end_at)}` : '未设置时间'}</small></div><span>{activeDay.total_duration_min} 分钟 · {activeDay.total_distance_km} km</span></div><div className="route-place-checks">{plan.places.map(place => <label key={place.id}><input type="checkbox" checked={selectedPlaces.includes(place.id)} onChange={event => setSelectedPlaces(rows => event.target.checked ? [...rows, place.id] : rows.filter(id => id !== place.id))}/><span>{place.name}</span>{place.must_visit && <em>必去</em>}</label>)}</div><div className="route-order-preview">{selectedPlaces.map((placeId, index) => { const place = plan.places.find(item => item.id === placeId); return place ? <span key={placeId}><b>{index + 1}</b>{place.name}{index < selectedPlaces.length - 1 && <ChevronRight size={13}/>}</span> : null })}</div><button className="primary-btn small" onClick={saveRoute} disabled={busy}><Route size={14}/>保存路线并计算距离</button></div>}</div><div className="panel travel-map-panel"><div className="panel-head"><div><h3>路线地图</h3><p>地点坐标使用 OpenStreetMap 搜索结果，距离采用免费估算。</p></div><Navigation size={18}/></div><TravelMap places={plan.places} nodes={activeDay?.nodes || []}/></div></div>
    <form className="panel travel-auto-panel" onSubmit={autoPlan}><div className="panel-head"><div><h3>自动规划路线</h3><p>生成距离最短、时间最省、景点最多和舒适度最高等方案。</p></div><RefreshCw size={18}/></div><div className="travel-form-grid"><label>规划日期（可选）<input name="travel_date" type="date" min={plan.start_date} max={plan.end_date}/></label><label>每日最大游玩时长（分钟）<input name="max_play_minutes" type="number" min="30" defaultValue="600"/></label><label>最早出发<input name="earliest_start" type="time" defaultValue="09:00"/></label><label>最晚结束<input name="latest_end" type="time" defaultValue="21:00"/></label><label>交通方式<select name="transport" defaultValue={plan.default_transport}><option value="drive">驾车</option><option value="transit">公交</option><option value="walk">步行</option><option value="bike">骑行</option></select></label><label>优先策略<select name="prioritize" defaultValue="balanced"><option value="balanced">综合平衡</option><option value="distance">距离最短</option><option value="time">时间最省</option><option value="places">景点最多</option><option value="comfort">舒适度最高</option></select></label></div><button className="primary-btn small" disabled={busy || !plan.places.length}><RefreshCw size={14}/>开始生成方案</button>{autoOptions.length > 0 && <div className="travel-options">{autoOptions.map(option => <div className="travel-option" key={option.option_id}><div><strong>{option.name}</strong><small>{option.description}</small></div><span><b>{option.score}</b> 分 · {option.total_distance_km} km · {option.total_duration_min} 分钟</span><button type="button" className="secondary-btn" onClick={() => applyOption(option.option_id)}>应用此方案</button></div>)}</div>}</form>
    <div className="travel-bottom-grid"><div className="panel travel-meeting-panel"><div className="panel-head"><div><h3>集合点推荐</h3><p>至少 2 名成员提交位置后计算平均距离和推荐指数。</p></div><Navigation size={18}/></div>{meeting ? meeting.ready ? <div className="meeting-result"><div className="meeting-recommended"><span>推荐集合点</span><strong>{meeting.recommended.name}</strong><small>{meeting.recommended.address}</small><b>{meeting.recommended.score}% 推荐指数 · 平均 {meeting.recommended.average_distance_km} km</b></div>{meeting.recommended.member_distances.map(member => <div className="meeting-member" key={member.user_id}><span>{member.user_name}</span><b>{member.distance_km} km</b></div>)}</div> : <div className="travel-inline-hint">{meeting.message}</div> : <div className="travel-inline-hint">点击“集合点推荐”生成方案。</div>}</div><div className="panel travel-publish-panel"><div className="panel-head"><div><h3>行程确认与同步</h3><p>发布前检查通过后，正式路线才能进入群组共享日程。</p></div><ClipboardCheck size={18}/></div>{checks && <div className={`publish-checks ${checks.passed ? 'passed' : 'failed'}`}><strong>{checks.passed ? '发布前检查通过' : '还有需要处理的问题'}</strong>{checks.errors.map(error => <small key={error}>• {error}</small>)}{checks.passed && <small>预算估算：¥{(checks.total_budget_cents / 100).toFixed(2)}</small>}</div>}{!checks && <div className="travel-inline-hint">未执行发布检查。</div>}{plan.status === 'published' && <button className="primary-btn small" onClick={syncCalendar}><CalendarDays size={14}/>同步到共享日程</button>}</div></div>
    {showCreate && <TravelPlanCreateModal onClose={() => setShowCreate(false)} onSubmit={createPlan} busy={busy}/>}</div>
}

function TravelPlanCreateModal({ onClose, onSubmit, busy }) {
  const today = new Date().toISOString().slice(0, 10)
  const nextWeek = new Date(Date.now() + 86400000 * 2).toISOString().slice(0, 10)
  return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><form className="modal travel-plan-modal" onSubmit={onSubmit}><button type="button" className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">NEW TRIP</span><h2>新建旅行计划</h2><p>先保存草稿，再逐步添加地点和每日路线。</p><label>旅行名称<input name="name" required placeholder="例如：上海周末城市漫游"/></label><label>主要目的地<input name="destination" required placeholder="例如：上海"/></label><div className="travel-form-grid"><label>出发日期<input name="start_date" type="date" required defaultValue={today}/></label><label>结束日期<input name="end_date" type="date" required defaultValue={nextWeek}/></label><label>默认出发城市<input name="departure_city" placeholder="例如：杭州"/></label><label>默认交通<select name="default_transport" defaultValue="drive"><option value="drive">驾车</option><option value="transit">公交</option><option value="walk">步行</option><option value="bike">骑行</option></select></label><label>预计人数<input name="estimated_people" type="number" min="1" defaultValue="2" required/></label><label>总预算（元）<input name="budget" type="number" min="0" step="0.01" defaultValue="0"/></label></div><label>默认出发点<input name="default_start_point" placeholder="例如：上海虹桥站"/></label><label>旅行备注<textarea name="notes" rows="3" placeholder="住宿偏好、注意事项等"/></label><button className="primary-btn" disabled={busy}>{busy ? '保存中…' : '保存为草稿'} <ArrowUpRight size={16}/></button></form></div>
}

function formatDate(value) { if (!value) return '-'; return new Date(value.replace(' ', 'T')).toLocaleDateString('zh-CN', {month:'short', day:'numeric'}) }
function formatDateTime(value) { if (!value) return '-'; return new Date(value.replace(' ', 'T')).toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'}) }
function ChatPanel({ groupId, user, notify }) {
  const [messages, setMessages] = useState([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false)
  const load = useCallback(() => api(`/groups/${groupId}/messages`).then(setMessages).catch(e => notify(e.message)), [groupId, notify])
  useEffect(() => { load(); const timer = setInterval(load, 5000); return () => clearInterval(timer) }, [load])
  const submit = async e => { e.preventDefault(); if (!text.trim() || busy) return; setBusy(true); try { const message = await api(`/groups/${groupId}/messages`, { method:'POST', body: JSON.stringify({content:text}) }); setMessages(items => [...items, message]); setText('') } catch (e) { notify(e.message) } finally { setBusy(false) } }
  return <div className="manager-panel chat-panel"><div className="manager-head"><div><h3>群聊</h3><p>和群成员实时交流，消息会自动刷新</p></div><MessageCircle size={18}/></div><div className="message-list">{messages.map(message => <div className={`message-row ${message.user_id === user.id ? 'mine' : ''}`} key={message.id}><Avatar initials={(message.group_nickname || message.nickname).slice(-2)} color={message.avatar_color}/><div><strong>{message.user_id === user.id ? '我' : (message.group_nickname || message.nickname)}</strong><p>{message.content}</p><small>{formatDateTime(message.created_at)}</small></div></div>)}{messages.length === 0 && <div className="empty-state">还没有消息，发起第一句聊天吧</div>}</div><form className="message-form" onSubmit={submit}><input value={text} onChange={e => setText(e.target.value)} maxLength="2000" placeholder="发送群消息..."/><button disabled={busy || !text.trim()}><Send size={16}/></button></form></div>
}
function composeDateTimeParts(date, hour, minute) {
  if (!date && !hour && !minute) return ''
  if (date && hour && minute) return `${date}T${hour}:${minute}`
  const partialTime = `${hour || ''}:${minute || ''}`
  return date ? (hour || minute ? `${date}T${partialTime}` : date) : partialTime
}
function splitDateTime(value) {
  const normalized = (value || '').replace(' ', 'T')
  const dateTimeMatch = normalized.match(/^(\d{4}-\d{2}-\d{2})T(\d{0,2}):(\d{0,2})$/)
  if (dateTimeMatch) return { date: dateTimeMatch[1], time: `${dateTimeMatch[2]}:${dateTimeMatch[3]}` }
  if (/^\d{0,2}:\d{0,2}$/.test(normalized) && normalized.includes(':')) return { date: '', time: normalized }
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return { date: normalized, time: '' }
  return { date: normalized.slice(0, 10), time: normalized.slice(11, 16) }
}
function DateTimeField({ label, value, onChange, required = false }) {
  const { date, time } = splitDateTime(value)
  const hour = time ? time.slice(0, 2) : ''
  const minute = time ? time.slice(3, 5) : ''
  const update = (nextDate, nextHour = hour, nextMinute = minute) => onChange(composeDateTimeParts(nextDate, nextHour, nextMinute))
  return <div className="datetime-field"><span className="datetime-label">{label}</span><div className="datetime-controls"><label><span>日期</span><input type="date" value={date} onChange={e => update(e.target.value)} required={required}/></label><label><span>小时</span><select value={hour} onChange={e => update(date, e.target.value, minute)} required={required}><option value="">选择小时</option>{Array.from({length: 24}, (_, hourValue) => <option key={hourValue} value={String(hourValue).padStart(2, '0')}>{String(hourValue).padStart(2, '0')} 时</option>)}</select></label><label><span>分钟</span><select value={minute} onChange={e => update(date, hour, e.target.value)} required={required}><option value="">选择分钟</option>{Array.from({length: 60}, (_, minuteValue) => <option key={minuteValue} value={String(minuteValue).padStart(2, '0')}>{String(minuteValue).padStart(2, '0')} 分</option>)}</select></label></div></div>
}

function LocationPickerMap({ locations, onPick }) {
  const points = locations.map(location => getMapPoint(location)).filter(Boolean)
  const center = points[0] || [31.2304, 121.4737]
  function MapClick() { useMapEvents({ click: event => onPick({ name: '地图选点', address: `${event.latlng.lat.toFixed(6)}, ${event.latlng.lng.toFixed(6)}`, lat: event.latlng.lat, lng: event.latlng.lng }) }); return null }
  return <MapContainer {...MAP_OPTIONS} center={center} zoom={12} className="location-map"><MapEffects center={center} zoom={12} points={points} fitBounds={false}/><MapTiles/><MapClick/>{locations.map((location, index) => { const point = getMapPoint(location); return point ? <Marker key={`${location.id || index}-${point[0]}-${point[1]}`} position={point}><Popup>{location.name}<br/>{location.address}</Popup></Marker> : null })}</MapContainer>
}

function LocationSearch({ onAdd }) {
  const [query, setQuery] = useState(''); const [results, setResults] = useState([]); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('')
  const search = async event => {
    event?.preventDefault()
    const value = query.trim()
    if (value.length < 2) { setResults([]); setMessage('请输入至少 2 个字后再搜索'); return }
    setBusy(true); setMessage('')
    try {
      const found = await api(`/geo/search?q=${encodeURIComponent(value)}`)
      setResults(found)
      setMessage(found.length ? '' : '没有找到匹配地点，请换一个关键词或直接在地图上点选')
    } catch (error) {
      setResults([]); setMessage(error.message || '地点搜索失败，请检查网络后重试')
    } finally { setBusy(false) }
  }
  return <div className="location-search"><div className="location-search-controls"><input value={query} onChange={event => { setQuery(event.target.value); if (message) setMessage('') }} onKeyDown={event => { if (event.key === 'Enter') search(event) }} placeholder="搜索餐厅、电影院、景点或会议地点"/><button type="button" className="secondary-btn" onClick={search} disabled={busy}>{busy ? '搜索中…' : '搜索地点'}</button></div>{message && <small className={`location-search-message ${results.length ? '' : 'error'}`}>{message}</small>}{results.map(result => <button type="button" className="location-result" key={`${result.lat}-${result.lng}`} onClick={() => { onAdd(result); setResults([]); setMessage('已选择地点，请补充信息后保存') }}><strong>{result.name}</strong><small>{result.address}</small></button>)}</div>
}

function LocationEditor({ mode, locations, setLocations }) {
  const add = location => setLocations(rows => rows.some(row => Math.abs(row.lat - location.lat) < 0.00001 && Math.abs(row.lng - location.lng) < 0.00001) ? rows : [...rows, location])
  return <div className="location-editor"><div className="location-editor-head"><div><strong>活动地点{mode === 'poll' ? '候选地点' : ''}</strong><small>{mode === 'poll' ? '在地图上添加至少两个候选地点，成员可投票。' : '可搜索或直接在地图上点选一个地点。'}</small></div></div><LocationSearch onAdd={add}/><LocationPickerMap locations={locations} onPick={add}/><div className="location-list">{locations.map((location, index) => <div className="location-row" key={`${location.lat}-${location.lng}`}><div><strong>{index + 1}. {location.name}</strong><small>{location.address || `${location.lat.toFixed(5)}, ${location.lng.toFixed(5)}`}</small></div><button type="button" onClick={() => setLocations(rows => rows.filter((_, rowIndex) => rowIndex !== index))}>移除</button></div>)}</div></div>
}

function ActivityCreateModal({ groupId, onClose, onSaved, notify }) {
  const [mode, setMode] = useState('fixed'); const [items, setItems] = useState([{title:'', start_at:'', end_at:'', note:''}]); const [locations, setLocations] = useState([]); const [busy, setBusy] = useState(false)
  const update = (index, key, value) => setItems(rows => rows.map((row, i) => i === index ? {...row, [key]: value} : row))
  const submit = async e => { e.preventDefault(); const data = new FormData(e.currentTarget); const incomplete = items.some(item => !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(item.start_at) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(item.end_at)); if (incomplete) { notify('请完整选择每个时间段的日期、小时和分钟'); return } setBusy(true); try { const starts = items.map(item => item.start_at); const ends = items.map(item => item.end_at); const payload = {title:data.get('title'), description:data.get('description'), mode, form:data.get('form'), start_at:starts.slice().sort()[0], end_at:ends.slice().sort().at(-1), items: mode === 'fixed' ? items : [], slots: mode === 'poll' ? items : [], locations, notice:data.get('notice')}; const result = await api(`/groups/${groupId}/activities`, {method:'POST', body:JSON.stringify(payload)}); onSaved(result); notify(mode === 'fixed' ? '活动已发布' : '投票已发布') } catch (e) { notify(e.message) } finally { setBusy(false) } }
  return <div className="modal-backdrop activity-backdrop"><form className="modal activity-modal" onSubmit={submit}><button type="button" className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">NEW ACTIVITY</span><h2>创建群组活动</h2><label>活动名称<input name="title" required placeholder="例如：周末户外日"/></label><label>活动说明<textarea name="description" rows="2" placeholder="集合地点、参与规则等"/></label><label>活动形式<input name="form" placeholder="例如：聚餐、唱歌、球类"/></label><div className="mode-switch"><button type="button" className={mode === 'fixed' ? 'active' : ''} onClick={() => setMode('fixed')}><Clock3 size={14}/>确定时间</button><button type="button" className={mode === 'poll' ? 'active' : ''} onClick={() => setMode('poll')}><Vote size={14}/>发起投票</button></div><p className="form-hint">{mode === 'fixed' ? '填写一个或多个连续的小活动，发布后所有成员可见。' : '填写多个候选时间段和地点，成员投票后由群主确定。'}</p><div className="time-format-hint">日期、小时和分钟均需单独选择，时间精确到分钟。</div>{items.map((item, index) => <div className="activity-item-fields" key={index}><div className="activity-item-title"><span>{mode === 'fixed' ? `小活动 ${index + 1}` : `候选时间 ${index + 1}`}</span><input value={item.title} onChange={e => update(index,'title',e.target.value)} required placeholder={mode === 'fixed' ? '填写活动内容，例如：吃饭' : '填写这个时间段的活动建议'}/></div><DateTimeField label="开始时间" value={item.start_at} onChange={value => update(index,'start_at',value)} required/><DateTimeField label="结束时间" value={item.end_at} onChange={value => update(index,'end_at',value)} required/><label className="activity-note-field"><span>补充说明</span><input value={item.note} onChange={e => update(index,'note',e.target.value)} placeholder={mode === 'fixed' ? '这个小活动的须知（可选）' : '对此时间段的其他建议（可选）'}/></label></div>)}<button type="button" className="secondary-btn" onClick={() => setItems(rows => [...rows, {title:'',start_at:'',end_at:'',note:''}])}><Plus size={14}/>增加{mode === 'fixed' ? '小活动' : '候选时间'}</button><LocationEditor mode={mode} locations={locations} setLocations={setLocations}/><label>活动须知<textarea name="notice" rows="2" placeholder="最终发布时展示给成员"/></label><button className="primary-btn" disabled={busy}>{busy ? '提交中...' : mode === 'fixed' ? '立即发布' : '发布投票'} <ArrowUpRight size={16}/></button></form></div>
}
function ActivityCard({ activity, canManage, canPublish, onVote, onEnd, onPublish }) {
  const [showVote, setShowVote] = useState(false); const [choices, setChoices] = useState({}); const [suggestions, setSuggestions] = useState({}); const [locationChoice, setLocationChoice] = useState(activity.my_location_vote?.location_id || ''); const [locationSuggestion, setLocationSuggestion] = useState(activity.my_location_vote?.suggestion || ''); const [publishing, setPublishing] = useState(false); const [showPublish, setShowPublish] = useState(false); const [publishChoices, setPublishChoices] = useState({}); const [publishTitles, setPublishTitles] = useState({}); const [publishNotice, setPublishNotice] = useState(activity.notice || ''); const [selectedLocation, setSelectedLocation] = useState(activity.selected_location_id || '')
  const submitVote = async () => { await onVote(activity.id, activity.slots.map(slot => ({slot_id:slot.id, available:Boolean(choices[slot.id]), suggestion:suggestions[slot.id] || ''})), locationChoice ? [{location_id:Number(locationChoice), suggestion:locationSuggestion}] : []); setShowVote(false) }
  const publish = async () => { const selected = activity.slots.filter(slot => publishChoices[slot.id]); if (!selected.length) return; setPublishing(true); await onPublish(activity.id, selected.map(slot => ({title:publishTitles[slot.id] || slot.suggestion || '群组活动', start_at:slot.start_at, end_at:slot.end_at, note:''})), publishNotice, selectedLocation || null); setPublishing(false); setShowPublish(false) }
  const locationSummary = location => `${location.name} · ${location.average_distance_km == null ? '暂无成员位置' : `${location.average_distance_km} 公里`}`
  return <article className="activity-card-item"><div className="activity-card-head"><div><span className={`status-chip ${activity.status}`}>{activity.status === 'published' ? '已发布' : activity.status === 'ended' ? '投票已结束' : '投票中'}</span><h3>{activity.title}</h3><p>{activity.description || '暂无活动说明'} · 发起人 {activity.creator_name}</p></div><CalendarDays size={20}/></div>{activity.status === 'published' ? <><div className="published-items">{activity.items.map(item => <div key={item.id}><strong>{item.title}</strong><span>{formatDateTime(item.start_at)} - {formatDateTime(item.end_at)}</span>{item.note && <small>{item.note}</small>}</div>)}</div>{activity.locations?.find(location => location.id === activity.selected_location_id) && <div className="selected-location"><strong>集合地点：{activity.locations.find(location => location.id === activity.selected_location_id).name}</strong><small>{activity.locations.find(location => location.id === activity.selected_location_id).address}</small></div>}<p className="activity-notice">{activity.notice || '暂无活动须知'}</p></> : <><div className="vote-summary"><span><ListChecks size={14}/> {activity.voted_count}/{activity.member_count} 人已投票</span>{activity.all_voted && <b>全部完成</b>}</div>{activity.locations?.length > 0 && <div className="location-score-list"><strong>候选地点综合评分</strong>{activity.locations.map(location => <div className="location-score-row" key={location.id}><div><b>{location.name}</b><small>{location.address}</small><small>{locationSummary(location)} · 投票 {location.vote_count} 人</small></div><strong>{location.score}%</strong></div>)}</div>}<div className="vote-bars">{activity.slots.map(slot => <div key={slot.id}><div className="vote-bar-label"><span>{formatDateTime(slot.start_at)} - {formatDateTime(slot.end_at)}</span><b>{slot.available_count} 人</b></div><div className="vote-bar"><i style={{width:`${activity.member_count ? slot.available_count / activity.member_count * 100 : 0}%`}}/></div>{slot.suggestion && <small>发起建议：{slot.suggestion}</small>}{slot.votes.filter(v => v.suggestion).map(v => <small key={v.id}>{v.group_nickname || v.nickname}：{v.suggestion}</small>)}</div>)}</div><div className="activity-actions"><button className="secondary-btn" onClick={() => setShowVote(!showVote)}><Vote size={14}/> {showVote ? '收起投票' : '填写时间和地点投票'}</button>{canManage && activity.status === 'open' && <button className="secondary-btn" onClick={() => onEnd(activity.id)}>结束投票</button>}{canPublish && activity.status === 'ended' && <button className="primary-btn small" disabled={publishing} onClick={() => setShowPublish(!showPublish)}><BarChart3 size={14}/>正式发布</button>}</div>{showVote && <div className="vote-form">{activity.slots.map(slot => <label key={slot.id}><input type="checkbox" checked={Boolean(choices[slot.id])} onChange={e => setChoices({...choices,[slot.id]:e.target.checked})}/><span>{formatDateTime(slot.start_at)} - {formatDateTime(slot.end_at)}</span><input value={suggestions[slot.id] || ''} onChange={e => setSuggestions({...suggestions,[slot.id]:e.target.value})} placeholder="对此时间段的活动建议"/></label>)}{activity.locations?.length > 0 && <label className="location-vote-field"><span>选择集合地点</span><select value={locationChoice} onChange={e => setLocationChoice(e.target.value)} required><option value="">请选择地点</option>{activity.locations.map(location => <option key={location.id} value={location.id}>{location.name} · {location.score}%</option>)}</select><input value={locationSuggestion} onChange={e => setLocationSuggestion(e.target.value)} placeholder="地点建议（可选）"/></label>}<button className="primary-btn small" onClick={submitVote}>提交投票</button></div>}{showPublish && <div className="vote-form publish-form"><strong>选择最终发布的小活动和地点</strong>{activity.locations?.length > 0 && <label><span>最终地点</span><select value={selectedLocation} onChange={e => setSelectedLocation(e.target.value)}><option value="">请选择地点</option>{activity.locations.map(location => <option key={location.id} value={location.id}>{location.name} · {location.score}%</option>)}</select></label>}{activity.slots.map(slot => <label key={slot.id}><input type="checkbox" checked={Boolean(publishChoices[slot.id])} onChange={e => setPublishChoices({...publishChoices,[slot.id]:e.target.checked})}/><span>{formatDateTime(slot.start_at)} - {formatDateTime(slot.end_at)}</span><input value={publishTitles[slot.id] || slot.suggestion || ''} onChange={e => setPublishTitles({...publishTitles,[slot.id]:e.target.value})} placeholder="最终活动内容"/></label>)}<textarea value={publishNotice} onChange={e => setPublishNotice(e.target.value)} rows="2" placeholder="活动须知"/><button className="primary-btn small" disabled={publishing} onClick={publish}>确认正式发布</button></div>}</>}</article>
}
function ActivitiesPanel({ groupId, detail, canManage, notify }) {
  const [activities, setActivities] = useState([]); const [showCreate, setShowCreate] = useState(false)
  const load = useCallback(() => api(`/groups/${groupId}/activities`).then(setActivities).catch(e => notify(e.message)), [groupId, notify]); useEffect(() => { load() }, [load])
  const shareLocation = () => { if (!navigator.geolocation) return notify('当前浏览器不支持位置共享'); navigator.geolocation.getCurrentPosition(async position => { try { await api(`/groups/${groupId}/location`, {method:'POST', body:JSON.stringify({lat:position.coords.latitude, lng:position.coords.longitude})}); await load(); notify('当前位置已用于集合便利度计算') } catch (error) { notify(error.message) } }, () => notify('未获得位置权限，仍可正常参与地点投票')) }
  const vote = async (id, choices, location_choices) => { try { const next = await api(`/groups/${groupId}/activities/${id}/vote`, {method:'POST',body:JSON.stringify({choices, location_choices})}); setActivities(rows => rows.map(row => row.id === id ? next : row)); notify('时间和地点投票已提交') } catch (e) { notify(e.message) } }
  const end = async id => { try { const next = await api(`/groups/${groupId}/activities/${id}/end-vote`, {method:'POST'}); setActivities(rows => rows.map(row => row.id === id ? next : row)); notify('投票已结束') } catch(e) { notify(e.message) } }
  const publish = async (id, items, notice, location_id) => { try { const next = await api(`/groups/${groupId}/activities/${id}/publish`, {method:'POST',body:JSON.stringify({items,notice,location_id})}); setActivities(rows => rows.map(row => row.id === id ? next : row)); notify('活动和集合地点已正式发布') } catch(e) { notify(e.message) } }
  return <div className="activities-panel"><div className="manager-panel activity-toolbar"><div><h3>群组活动</h3><p>固定活动直接发布，投票活动由成员协商后确定</p></div><div className="activity-toolbar-actions"><button className="secondary-btn" onClick={shareLocation}>共享我的位置</button>{canManage && <button className="primary-btn small" onClick={() => setShowCreate(true)}><Plus size={15}/>创建活动</button>}</div></div>{activities.length ? activities.map(activity => <ActivityCard key={activity.id} activity={activity} canManage={canManage} canPublish={detail.current_role === 'owner'} onVote={vote} onEnd={end} onPublish={publish}/>) : <div className="empty-page compact-empty"><CalendarDays size={28}/><h3>还没有活动</h3><p>{canManage ? '创建一次固定活动或发起时间投票。' : '等待群主或管理员发布活动。'}</p></div>}{showCreate && <ActivityCreateModal groupId={groupId} onClose={() => setShowCreate(false)} onSaved={result => { setActivities(rows => [result, ...rows]); setShowCreate(false) }} notify={notify}/>}</div>
}
function GroupOverview({ detail, setView, _notify, onOpenBills }) { return <div className="overview-grid"><div className="manager-panel announcement-card"><div className="panel-icon mint"><Megaphone size={18}/></div><div><small>群公告</small><h3>{detail.announcement || '暂无群公告'}</h3><p>{detail.announcement ? '公告对所有群成员可见。' : '在群组设置中添加第一条公告。'}</p></div></div><div className="manager-panel metric-card"><small>成员构成</small><strong>{detail.people}</strong><p>{detail.members_detail.filter(m => m.role === 'admin').length} 位管理员</p><button onClick={() => setView('members')}>管理成员 <ArrowUpRight size={14}/></button></div><div className="manager-panel metric-card"><small>本期群组支出</small><strong>{detail.amount}</strong><p>所有账单均可追溯至付款人与参与成员</p><button onClick={() => onOpenBills?.(detail.id)}>查看账单 <ArrowUpRight size={14}/></button></div><div className="manager-panel activity-card"><div className="manager-head"><div><h3>成员活跃度</h3><p>依据群组操作、管理与协作次数动态计算</p></div></div>{detail.members_detail.slice().sort((a,b) => b.activity_score-a.activity_score).slice(0,4).map(member => <div className="activity-row" key={member.id}><Avatar initials={member.initials} color={member.avatar_color}/><span>{member.display_name}</span><div><i style={{width:`${member.activity_score}%`}}/></div><b>{member.activity_score}</b></div>)}</div></div> }

function InvitePanel({ detail, canManage, act, notify }) { const joinLink=`${window.location.origin}/join/${detail.invite_code}`; return <div className="invite-grid"><div className="manager-panel invite-card"><div className="panel-icon blue"><Link2 size={18}/></div><h3>邀请成员</h3>{canManage ? <><p>邀请码将在 {formatDate(detail.invite_expires_at)} 失效，加入方式：{detail.join_requires_approval ? '需要审核' : '直接加入'}。</p><div className="qr-block"><QRCodeSVG value={joinLink} size={112} bgColor="#ffffff" fgColor="#403747" level="M"/><span>扫码打开入群申请</span></div><div className="invite-code"><strong>{detail.invite_code}</strong><button onClick={() => { navigator.clipboard?.writeText(detail.invite_code); notify('邀请码已复制') }}><Copy size={15}/></button></div><button className="secondary-btn" onClick={() => { navigator.clipboard?.writeText(joinLink); notify('邀请链接已复制') }}><Link2 size={14}/>复制邀请链接</button><button className="secondary-btn" onClick={() => act(() => api(`/groups/${detail.id}/invite`, {method:'POST', body:JSON.stringify({valid_days:7})}), '邀请已更新')}>生成新邀请</button></> : <p>只有群主和管理员可以查看或更新邀请。</p>}</div><div className="manager-panel request-card"><div className="manager-head"><div><h3>入群审核</h3><p>{canManage ? `${detail.join_requests.length} 条待处理申请` : '管理员可处理申请'}</p></div></div>{detail.join_requests.map(request => <div className="request-row" key={request.id}><Avatar initials={request.nickname.slice(-2)} color={request.avatar_color}/><div><strong>{request.nickname}</strong><small>@{request.username} · {formatDate(request.created_at)} 申请</small></div><button className="approve" onClick={() => act(() => api(`/groups/${detail.id}/requests/${request.id}/review`, {method:'POST',body:JSON.stringify({decision:'approved'})}), '已通过入群申请', true)}><CheckCircle2 size={16}/></button><button className="reject" onClick={() => act(() => api(`/groups/${detail.id}/requests/${request.id}/review`, {method:'POST',body:JSON.stringify({decision:'rejected'})}), '已拒绝入群申请')}><XCircle size={16}/></button></div>)}{detail.join_requests.length === 0 && <div className="empty-state"><Check size={18}/>当前没有待审核申请</div>}</div></div> }

function GroupSettings({ detail, act, refresh }) { const save = event => { event.preventDefault(); const data = new FormData(event.currentTarget); act(() => api(`/groups/${detail.id}`, {method:'PATCH',body:JSON.stringify({name:data.get('name'),type:data.get('type'),announcement:data.get('announcement'),theme_color:data.get('theme_color'),cover_style:data.get('cover_style'),join_requires_approval:data.get('approval') === 'on'})}), '群组设置已保存', true) }; return <div className="settings-grid"><form className="manager-panel group-settings-form" onSubmit={save}><div className="manager-head"><div><h3>群组资料与外观</h3><p>公告、主题和封面会同步给所有成员</p></div><Palette size={18}/></div><label>群组名称<input name="name" defaultValue={detail.name} required/></label><div className="form-row"><label>类型<select name="type" defaultValue={detail.type}><option>好友</option><option>旅行</option><option>宿舍</option><option>合租</option><option>聚餐</option></select></label><label>主题色<select name="theme_color" defaultValue={detail.theme_color}><option value="mint">薄荷绿</option><option value="lavender">雾紫</option><option value="peach">暖杏</option><option value="blue">浅蓝</option><option value="rose">柔粉</option></select></label></div><label>群公告<textarea name="announcement" defaultValue={detail.announcement} rows="3"/></label><label>封面样式<select name="cover_style" defaultValue={detail.cover_style}><option value="waves">流线</option><option value="grid">网格</option><option value="home">居家</option><option value="sun">日光</option></select></label><label className="toggle-line"><input type="checkbox" name="approval" defaultChecked={detail.join_requires_approval}/><span>新成员加入时需要管理员审核</span></label><button className="primary-btn small">保存设置</button></form><DangerZone detail={detail} act={act} refresh={refresh}/></div> }

function DangerZone({ detail, act }) { const [target, setTarget] = useState(''); const transferable = detail.members_detail.filter(m => m.role !== 'owner'); return <div className="manager-panel danger-zone"><h3>成员关系与群组状态</h3><p>转让、退出和解散都是重要操作，请谨慎执行。</p>{detail.current_role === 'owner' && <><label>转让群主<select value={target} onChange={e => setTarget(e.target.value)}><option value="">选择新群主</option>{transferable.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label><button disabled={!target} onClick={() => act(() => api(`/groups/${detail.id}/transfer`, {method:'POST',body:JSON.stringify({new_owner_id:Number(target)})}), '群主已转让', true)}><Crown size={15}/>确认转让</button><button className="danger" onClick={() => window.confirm('确定解散该群组？解散后群组将不再显示。') && act(() => api(`/groups/${detail.id}`, {method:'DELETE'}), '群组已解散', true, false)}><Trash2 size={15}/>解散群组</button></>}{detail.current_role !== 'owner' && <button className="danger" onClick={() => window.confirm('确定退出该群组？') && act(() => api(`/groups/${detail.id}/leave`, {method:'POST'}), '已退出群组', true, false)}><LogOutIcon size={15}/>退出群组</button>}</div> }

function MemberModal({ member, detail, currentUser, onClose, onSave, onRemove }) { const submit = event => { event.preventDefault(); const data = new FormData(event.currentTarget); onSave({role:data.get('role') || null,group_nickname:data.get('group_nickname'),member_note:data.get('member_note')}) }; const isOwner = detail.current_role === 'owner'; const canManage = ['owner','admin'].includes(detail.current_role); return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><form className="modal member-modal" onSubmit={submit}><button type="button" className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">MEMBER PROFILE</span><h2>成员资料</h2><div className="profile-preview"><Avatar initials={member.initials} color={member.avatar_color}/><div><strong>{member.display_name}</strong><small>@{member.username}</small></div></div><label>群内昵称<input name="group_nickname" defaultValue={member.group_nickname || ''} disabled={!canManage && member.id !== currentUser.id}/></label>{canManage && <label>成员备注<input name="member_note" defaultValue={member.member_note || ''} placeholder="仅群组管理员可见"/></label>}{isOwner && member.role !== 'owner' && member.id !== currentUser.id && <label>角色<select name="role" defaultValue={member.role}><option value="admin">管理员</option><option value="member">普通成员</option></select></label>}<button className="primary-btn">保存成员资料</button>{canManage && member.role !== 'owner' && member.id !== currentUser.id && <button type="button" className="remove-member" onClick={() => window.confirm(`确定移除 ${member.display_name}？`) && onRemove()}><Trash2 size={14}/>移出群组</button>}</form></div> }

function JoinGroupModal({ initialCode = '', onClose, onJoined }) { const [error,setError]=useState(''); const submit=async event=>{event.preventDefault();setError('');const code=new FormData(event.currentTarget).get('code');try{const result=await api('/groups/join',{method:'POST',body:JSON.stringify({invite_code:code})});onJoined(result.status==='pending'?`已申请加入“${result.group_name}”，等待审核`:`已加入“${result.group_name}”`)}catch(requestError){setError(requestError.message)}}; return <div className="modal-backdrop" onMouseDown={event => event.target===event.currentTarget&&onClose()}><form className="modal" onSubmit={submit}><button type="button" className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">JOIN A GROUP</span><h2>使用邀请码加入</h2><p>输入群管理员分享的 8 位邀请码。</p><label>邀请码<input name="code" required minLength="6" placeholder="例如：A1B2C3D4" defaultValue={initialCode}/></label>{error&&<div className="form-error">{error}</div>}<button className="primary-btn">申请加入 <ArrowUpRight size={16}/></button></form></div> }
function CalendarView({ notify }) {
  const [activities, setActivities] = useState([]); const [availability, setAvailability] = useState([]); const [groups, setGroups] = useState([]); const [busy, setBusy] = useState(false); const [now] = useState(() => Date.now())
  const load = useCallback(async () => { try { const [nextActivities, nextAvailability, nextGroups] = await Promise.all([api('/calendar'), api('/calendar/availability'), api('/groups')]); setActivities(nextActivities); setAvailability(nextAvailability); setGroups(nextGroups) } catch (error) { notify(error.message) } }, [notify])
  useEffect(() => { load() }, [load])
  const saveAvailability = async event => { event.preventDefault(); if (busy) return; const data = new FormData(event.currentTarget); const visibility = data.get('visibility'); setBusy(true); try { await api('/calendar/availability', {method:'POST', body:JSON.stringify({start_at:data.get('start_at'), end_at:data.get('end_at'), visibility, group_id:visibility === 'group' ? Number(data.get('group_id')) : null, note:data.get('note') || ''})}); event.currentTarget.reset(); await load(); notify('空闲时间已保存') } catch (error) { notify(error.message) } finally { setBusy(false) } }
  const removeAvailability = async id => { try { await api(`/calendar/availability/${id}`, {method:'DELETE'}); setAvailability(rows => rows.filter(row => row.id !== id)); notify('空闲时间已删除') } catch (error) { notify(error.message) } }
  const upcoming = activities.filter(activity => { const time = Date.parse((activity.start_at || '').replace(' ', 'T')); return Number.isFinite(time) && time >= now }).length
  return <section className="calendar-page"><div className="calendar-banner"><div><span className="label-chip"><CalendarDays size={13} /> 我的日程</span><h2>空闲与行程<br /><em>都安排清楚</em></h2><p>已确定的群组活动会自动加入；空闲时间可选择是否让群友看到。</p></div><div className="calendar-orb">{activities.length}<span>项已确定行程</span></div></div><div className="calendar-summary"><span><CheckCircle2 size={16}/>已确定行程 <b>{activities.length}</b></span><span><Clock3 size={16}/>待开始提醒 <b>{upcoming}</b></span><span><Users size={16}/>我的空闲时段 <b>{availability.length}</b></span></div><div className="calendar-layout"><div className="panel calendar-panel"><div className="panel-head"><div><h3>已确定行程</h3><p>正式发布的固定活动和投票后确认的活动</p></div></div>{activities.map(activity => <div className="time-slot recommended" key={activity.id}><div><strong>{activity.title}</strong><small>{activity.group_name} · {formatDateTime(activity.start_at)} - {formatDateTime(activity.end_at)}</small>{activity.items.map(item => <small key={item.id}>　• {item.title}：{formatDateTime(item.start_at)} - {formatDateTime(item.end_at)}</small>)}{activity.locations?.find(location => location.id === activity.selected_location_id) && <small>　• 集合地点：{activity.locations.find(location => location.id === activity.selected_location_id).name}（{activity.locations.find(location => location.id === activity.selected_location_id).address}）</small>}{activity.notice && <small>须知：{activity.notice}</small>}</div><span>{activity.reminder_label || '已确定'}</span></div>)}{activities.length === 0 && <div className="empty-state"><Check size={20}/>暂无已确定行程</div>}</div><div className="calendar-side"><form className="panel availability-form" onSubmit={saveAvailability}><div className="panel-head"><div><h3>添加空闲时间</h3><p>精确到日期、小时和分钟</p></div><Clock3 size={18}/></div><label>开始时间<input name="start_at" type="datetime-local" required/></label><label>结束时间<input name="end_at" type="datetime-local" required/></label><label>可见范围<select name="visibility" defaultValue="private"><option value="private">仅自己可见</option><option value="group">群友可见</option></select></label><label>共享到群组<select name="group_id" defaultValue=""><option value="">选择群组（仅群友可见时需要）</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><label>备注（可选）<input name="note" maxLength="200" placeholder="例如：晚上有空"/></label><button className="primary-btn small" disabled={busy}>{busy ? '保存中...' : '保存空闲时间'} <Check size={15}/></button></form><div className="panel availability-panel"><div className="panel-head"><div><h3>我的空闲时间</h3><p>群友可见时会显示在对应群组的协作视图</p></div></div>{availability.map(slot => <div className="availability-row" key={slot.id}><div><strong>{formatDateTime(slot.start_at)} - {formatDateTime(slot.end_at)}</strong><small>{slot.visibility === 'group' ? `群友可见${slot.group_id ? ` · ${groups.find(group => group.id === slot.group_id)?.name || '群组'}` : ''}` : '仅自己可见'}{slot.note ? ` · ${slot.note}` : ''}</small></div><button title="删除空闲时间" onClick={() => removeAvailability(slot.id)}><Trash2 size={14}/></button></div>)}{availability.length === 0 && <div className="empty-state"><Clock3 size={18}/>还没有设置空闲时间</div>}</div></div></div></section>
}
function WalletView({ notify, dashboard, groupId, onClearGroup }) {
  const [records, setRecords] = useState([]); const [filter, setFilter] = useState('all'); const [sort, setSort] = useState('latest'); const [expanded, setExpanded] = useState(null); const [busy, setBusy] = useState(false)
  const load = useCallback(() => api('/ai-bills').then(setRecords).catch(error => notify(error.message)), [notify])
  useEffect(() => { load() }, [load])
  useEffect(() => { setExpanded(null) }, [groupId])
  const visible = records.filter(record => !groupId || String(record.group_id) === String(groupId)).filter(record => {
    if (filter === 'unpaid') return record.my_payment_status === 'unpaid'
    if (filter === 'paid') return record.my_payment_status === 'paid'
    if (filter === 'confirmation') return record.workflow_status === 'pending_confirmation'
    if (filter === 'archived') return record.workflow_status === 'archived'
    return true
  }).slice().sort((a, b) => {
    if (sort === 'oldest') return String(a.created_at).localeCompare(String(b.created_at))
    if (sort === 'amount_desc') return Number(b.bill?.total_cents || 0) - Number(a.bill?.total_cents || 0)
    if (sort === 'amount_asc') return Number(a.bill?.total_cents || 0) - Number(b.bill?.total_cents || 0)
    if (sort === 'unpaid') return Number(b.my_payment_status === 'unpaid') - Number(a.my_payment_status === 'unpaid') || String(b.created_at).localeCompare(String(a.created_at))
    return String(b.created_at).localeCompare(String(a.created_at))
  })
  const complete = async (record, transfer) => {
    if (busy || transfer.status === 'completed') return
    setBusy(true)
    try { await api(`/groups/${record.group_id}/ai-bills/${record.id}/transfers/${transfer.id}/complete`, {method:'POST'}); await load(); notify('已确认付款') }
    catch (error) { notify(error.message) } finally { setBusy(false) }
  }
  const statusLabel = record => record.workflow_status === 'pending_confirmation' ? '待群主确认' : record.workflow_status === 'archived' ? '已归档' : record.my_payment_status === 'unpaid' ? '待付款' : record.my_payment_status === 'paid' ? '已付款' : '进行中'
  return <section className="wallet-page"><div className="wallet-hero"><div><span className="label-chip"><WalletCards size={13} /> 个人收支</span><h2>每一笔付出<br /><em>都有回应</em></h2><p>收入、支出与待确认款项，都清晰地记录在这里。</p></div><div className="wallet-number">¥ {Number(dashboard.stats.expense || 0).toFixed(2)}<small>累计支出 · 收入 ¥{Number(dashboard.stats.income || 0).toFixed(2)}</small></div></div><div className="panel bill-records-panel"><div className="panel-head"><div><h3>AI 分账记录</h3><p>{groupId ? '当前群组的分账方案' : '每笔分账只显示一条，点击查看完整现金流'}</p></div><button className="text-btn" onClick={() => { onClearGroup?.(); load() }}>刷新记录 <Sparkles size={14} /></button></div><div className="bill-record-toolbar"><div className="filter-tabs">{[['all','全部'],['unpaid','待付款'],['paid','已付款'],['confirmation','待群主确认'],['archived','已归档']].map(([key,label]) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div><select value={sort} onChange={event => setSort(event.target.value)} aria-label="排序方式"><option value="latest">最新</option><option value="oldest">最早</option><option value="amount_desc">金额从高到低</option><option value="amount_asc">金额从低到高</option><option value="unpaid">未付款优先</option></select></div>{visible.map(record => <article className={`bill-record ${expanded === record.id ? 'expanded' : ''}`} key={record.id}><button className="bill-record-summary" onClick={() => setExpanded(expanded === record.id ? null : record.id)}><div><strong>{record.title}</strong><small>{record.group_name} · {formatDateTime(record.created_at)}</small></div><b>{money(record.bill?.total_cents)}</b><span className={`status-chip ${record.workflow_status}`}>{statusLabel(record)}</span><ChevronDown size={16}/></button>{expanded === record.id && <div className="bill-record-detail"><p className="ai-explanation">{record.explanation || record.instruction}</p><div className="bill-detail-grid"><div><span>票据总额</span><strong>{money(record.bill?.total_cents)}</strong></div><div><span>分账状态</span><strong>{statusLabel(record)}</strong></div></div>{record.bill?.items?.length > 0 && <div className="bill-items-detail"><strong>消费明细</strong>{record.bill.items.map((item, index) => <div key={`${item.name}-${index}`}><span>{item.name}</span><b>{money(item.amount_cents)}</b></div>)}</div>}<div className="transfer-list"><strong>转账现金流</strong>{record.transfers.map(transfer => <div className="transfer-row" key={transfer.id}><span>{transfer.from_nickname} → {transfer.to_nickname}</span><b>{money(transfer.amount_cents)}</b>{transfer.from_user_id === record.my_transfers?.[0]?.from_user_id && transfer.status !== 'completed' && record.status === 'active' ? <button className="secondary-btn" disabled={busy} onClick={() => complete(record, transfer)}>确认已付款</button> : transfer.status === 'completed' ? <em>已完成</em> : <small>等待付款</small>}</div>)}</div>{record.status === 'active' && record.my_payment_status === 'unpaid' && <p className="payment-guidance">完成向收款人的转账后，在对应明细点击“确认已付款”。</p>}{record.status === 'pending' && <p className="payment-guidance">群主确认发布后，成员即可按明细完成付款。</p>}{record.status === 'archived' && <p className="payment-guidance">这笔集体转账已归档，仅供查看。</p>}</div>}</article>)}{visible.length === 0 && <div className="empty-state"><Check size={20}/>暂无符合条件的分账记录</div>}</div>{dashboard.pending_payments?.length > 0 && <div className="panel"><div className="panel-head"><div><h3>其他待处理款项</h3><p>来自旧版账单的付款和收款记录（暂不支持操作）</p></div></div>{dashboard.pending_payments.map((item, index) => <div className="payment-row" key={`legacy-${item.id}`}><Avatar initials={item.status === 'pending_in' ? 'IN' : 'OUT'} index={index}/><span>{item.status === 'pending_in' ? <><strong>{item.group_name}</strong> 有一笔款项待你确认</> : <>你需要完成 <strong>{item.group_name}</strong> 的付款</>}</span><b className={item.status === 'pending_in' ? 'positive' : ''}>¥ {Number(item.amount).toFixed(2)}</b></div>)}</div>}</section>
}

function money(cents) { return `¥ ${(Number(cents || 0) / 100).toFixed(2)}` }
function AIBillView({ groups, user, notify, target, onDataChanged }) {
  const [groupId, setGroupId] = useState(String(target?.groupId || groups[0]?.id || '')); const [detail, setDetail] = useState(null); const [payerId, setPayerId] = useState(user.id); const [instruction, setInstruction] = useState(''); const [files, setFiles] = useState([]); const [bills, setBills] = useState([]); const [busy, setBusy] = useState(false)
  const selectedGroup = groups.find(group => String(group.id) === String(groupId)); const isOwner = detail?.current_role === 'owner'; const load = useCallback(async () => { if (!groupId) return; try { const [nextDetail, nextBills] = await Promise.all([api(`/groups/${groupId}`), api(`/groups/${groupId}/ai-bills`)]); setDetail(nextDetail); setBills(nextBills) } catch (error) { notify(error.message) } }, [groupId, notify])
  useEffect(() => {
    const requested = target?.groupId ? String(target.groupId) : ''
    const available = groups.some(group => String(group.id) === String(groupId))
    if (requested && groups.some(group => String(group.id) === requested) && requested !== String(groupId)) setGroupId(requested)
    else if (!available && groups.length) setGroupId(String(groups[0].id))
  }, [target?.groupId, groups, groupId])
  useEffect(() => { setDetail(null); setBills([]) }, [groupId])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (detail && !detail.members_detail.some(member => Number(member.id) === Number(payerId))) setPayerId(detail.members_detail.find(member => Number(member.id) === Number(user.id))?.id || detail.members_detail[0]?.id || '') }, [detail, payerId, user.id])
  useEffect(() => { if (target?.billId && bills.some(bill => bill.id === target.billId)) document.getElementById(`ai-bill-${target.billId}`)?.scrollIntoView({behavior:'smooth', block:'center'}) }, [target?.billId, bills])
  const analyze = async event => { event.preventDefault(); if (!files.length) return notify('请先上传至少一张小票图片'); setBusy(true); try { const form = new FormData(); form.append('instruction', instruction); form.append('payer_id', payerId); files.forEach(file => form.append('files', file)); const result = await api(`/groups/${groupId}/ai-bills/analyze`, { method:'POST', body:form }); setBills(rows => [result, ...rows.filter(row => row.id !== result.id)]); await onDataChanged?.(); notify('AI 已完成识别，方案已生成并等待群主确认') } catch (error) { notify(error.message) } finally { setBusy(false) } }
  const action = async (billId, path, success) => { try { await api(`/groups/${groupId}/ai-bills/${billId}/${path}`, {method:'POST'}); await load(); await onDataChanged?.(); notify(success) } catch (error) { notify(error.message) } }
  const memberName = id => detail?.members_detail.find(member => member.id === id)?.display_name || `成员 ${id}`
  return <section className="ai-bill-page"><div className="ai-bill-hero"><div><span className="label-chip"><ReceiptText size={13}/> AI 票据分账</span><h2>上传小票，<br/><em>自动算清每一笔转账</em></h2><p>Qwen 识别商品和金额，服务器按你的自然语言规则重新计算并生成可审计的现金流方案。</p></div><div className="ai-bill-hero-icon"><ReceiptText size={34}/></div></div><div className="ai-bill-layout"><form className="panel ai-bill-form" onSubmit={analyze}><div className="panel-head"><div><h3>生成分账方案</h3><p>先选择群组、实际垫付人，再上传一张或多张小票。</p></div></div><label>目标群组<select value={groupId} onChange={e => setGroupId(e.target.value)} required><option value="">请选择群组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name} · {group.people} 人</option>)}</select></label><label>实际付款人<select value={payerId} onChange={e => setPayerId(Number(e.target.value))} required>{(detail?.members_detail || []).map(member => <option key={member.id} value={member.id}>{member.display_name}（@{member.username}）</option>)}</select></label><label>分账规则<textarea value={instruction} onChange={e => setInstruction(e.target.value)} rows="4" required /></label><label className="receipt-upload"><span><UploadCloud size={18}/>上传小票图片</span><input type="file" accept="image/*" multiple onChange={e => setFiles(Array.from(e.target.files || []))}/><small>{files.length ? `已选择 ${files.length} 张：${files.map(file => file.name).join('、')}` : '支持 JPG、PNG 等图片，最多 8 张'}</small></label><button className="primary-btn" disabled={busy || !groupId}>{busy ? 'AI 分析中...' : '识别并生成分账方案'} <ArrowUpRight size={16}/></button></form><div className="ai-bill-list"><div className="section-head compact"><div><h3>分账方案</h3><p>{selectedGroup ? `${selectedGroup.name} 的 AI 分账记录` : '选择目标群组后查看方案'}</p></div></div>{bills.map(bill => <AIBillCard key={bill.id} bill={bill} user={user} isOwner={isOwner} memberName={memberName} onAction={action}/>) }{!bills.length && <div className="empty-page compact-empty"><ReceiptText size={28}/><h3>还没有 AI 分账</h3><p>上传小票并描述分账规则，生成第一笔方案。</p></div>}</div></div></section>
}
function AIBillCard({ bill, user, isOwner, memberName, onAction }) {
  const allDone = bill.transfers.length > 0 && bill.transfers.every(transfer => transfer.status === 'completed'); const total = bill.bill?.total_cents || 0
  return <article id={`ai-bill-${bill.id}`} className="ai-bill-card"><div className="ai-bill-card-head"><div><span className={`status-chip ${bill.status}`}>{bill.status === 'pending' ? '待群主确认' : bill.status === 'active' ? '转账进行中' : '已归档'}</span><h3>{bill.title}</h3><p>{bill.bill?.category || '其他'} · {bill.bill?.receipts?.length || 1} 张小票 · 总额 {money(total)}</p></div><ReceiptText size={20}/></div><p className="ai-explanation">{bill.explanation || bill.instruction}</p><div className="ai-bill-items">{(bill.bill?.items || []).map((item, index) => <div key={`${item.receipt_index}-${index}`}><span>{item.name}</span><b>{money(item.amount_cents)}</b><small>承担人：{item.participant_ids.map(memberName).join('、')}</small></div>)}</div><div className="transfer-list"><strong>转账现金流</strong>{bill.transfers.map(transfer => <div className="transfer-row" key={transfer.id || `${transfer.from_user_id}-${transfer.to_user_id}`}><span>{transfer.from_nickname || memberName(transfer.from_user_id)} → {transfer.to_nickname || memberName(transfer.to_user_id)}</span><b>{money(transfer.amount_cents)}</b>{bill.status === 'active' && transfer.from_user_id === user.id && <button className="secondary-btn" disabled={transfer.status === 'completed'} onClick={() => onAction(bill.id, `transfers/${transfer.id}/complete`, '已标记转账完成')}>{transfer.status === 'completed' ? '已完成' : '完成转账'}</button>}{transfer.status === 'completed' && <em>已完成</em>}</div>)}</div>{bill.status === 'pending' && isOwner && <button className="primary-btn small" onClick={() => onAction(bill.id, 'activate', '分账方案已确认，成员可以开始转账')}>群主确认并发布方案</button>}{bill.status === 'pending' && !isOwner && <small className="pending-hint">方案已同步给所有群成员，正在等待群主确认发布。</small>}{bill.status === 'active' && isOwner && <button className="primary-btn small" disabled={!allDone} onClick={() => onAction(bill.id, 'archive', '分账方案已归档')}>群主归档本次分账</button>}{bill.status === 'active' && !allDone && <small className="pending-hint">等待所有转账完成后，群主才可以归档。</small>}</article>
}

function financeMonthLabel(month) {
  if (!/^\d{4}-\d{2}$/.test(month || '')) return month || '-'
  return new Date(`${month}-01T00:00:00`).toLocaleDateString('zh-CN', {year:'numeric', month:'long'})
}

function FinancialMap({ current = [], previous = [] }) {
  const currentMapped = current.map(point => ({ point, coords: getMapPoint(point) })).filter(item => item.coords)
  const previousMapped = previous.map(point => ({ point, coords: getMapPoint(point) })).filter(item => item.coords)
  const all = [...currentMapped, ...previousMapped]
  const points = all.map(item => item.coords)
  const center = points[0] || [31.2304, 121.4737]
  const maximum = Math.max(1, ...all.map(item => Number(item.point.amount_cents || 0)))
  const radius = point => 9 + Math.sqrt(Number(point.amount_cents || 0) / maximum) * 19
  return <div className="finance-map-wrap"><MapContainer {...MAP_OPTIONS} center={center} zoom={all.length ? 11 : 4} className="finance-map"><MapEffects center={center} zoom={all.length ? 11 : 4} points={points}/><MapTiles/>{previousMapped.map(({ point, coords }) => <CircleMarker key={`previous-${point.expense_id}`} center={coords} radius={radius(point)} pathOptions={{color:'#587fa8', fillColor:'#7ca6cf', fillOpacity:.18, weight:2, dashArray:'5 4'}}><Tooltip><strong>{point.merchant}</strong><br/>{point.group_name} · {money(point.amount_cents)}<br/>上月消费</Tooltip></CircleMarker>)}{currentMapped.map(({ point, coords }) => <CircleMarker key={`current-${point.expense_id}`} center={coords} radius={radius(point)} pathOptions={{color:'#9b4857', fillColor:'#d46a74', fillOpacity:.56, weight:2}}><Tooltip><strong>{point.merchant}</strong><br/>{point.group_name} · {point.category}<br/>{money(point.amount_cents)}</Tooltip></CircleMarker>)}</MapContainer>{!all.length && <div className="finance-map-empty"><MapPin size={20}/><span>当前筛选范围还没有已标注地点的消费</span></div>}</div>
}

function ExpenseLocationEditor({ expense, onSaved, onClose, notify }) {
  const [selection, setSelection] = useState([])
  const [busy, setBusy] = useState(false)
  const choose = location => setSelection([{name:location.name || expense.merchant, address:location.address || '', lat:Number(location.lat), lng:Number(location.lng)}])
  const save = async () => {
    if (!selection[0] || busy) return notify('请先搜索地点或在地图上选点')
    setBusy(true)
    try {
      await api(`/finance/expenses/${expense.expense_id}/location`, {method:'PATCH', body:JSON.stringify(selection[0])})
      notify('消费地点已保存，热力图已更新')
      await onSaved()
    } catch (error) { notify(error.message) } finally { setBusy(false) }
  }
  return <div className="finance-location-editor"><div className="finance-location-head"><div><strong>标注“{expense.merchant}”的消费地点</strong><small>{expense.group_name} · {expense.spent_at} · {money(expense.amount_cents)}</small></div><button title="关闭地点编辑" onClick={onClose}><X size={16}/></button></div><LocationSearch onAdd={choose}/><LocationPickerMap locations={selection} onPick={choose}/>{selection[0] && <div className="location-row"><div><strong>{selection[0].name}</strong><small>{selection[0].address}</small></div></div>}<button className="primary-btn small" disabled={busy || !selection[0]} onClick={save}>{busy ? '保存中...' : '保存消费地点'} <Check size={14}/></button></div>
}

function FinanceAnalytics({ groups, notify }) {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [groupId, setGroupId] = useState('')
  const [category, setCategory] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editingExpense, setEditingExpense] = useState(null)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({month})
      if (groupId) params.set('group_id', groupId)
      if (category) params.set('category', category)
      setData(await api(`/finance/analytics?${params}`))
    } catch (error) { notify(error.message) } finally { setLoading(false) }
  }, [month, groupId, category, notify])
  useEffect(() => { load() }, [load])
  const summary = data?.summary || {current_total_cents:0, previous_total_cents:0, expense_count:0, located_count:0, coverage_percent:0, change_percent:null}
  const changeText = summary.change_percent === null ? '上月无可比记录' : `${summary.change_percent >= 0 ? '+' : ''}${summary.change_percent}%`
  const maxMerchant = Math.max(1, ...(data?.merchant_ranking || []).map(row => row.amount_cents))
  return <section className="finance-page">
    <div className="finance-banner"><div><span className="label-chip"><ChartNoAxesCombined size={13}/> GROUP FINANCE</span><h2>看见消费发生在哪里，<br/><em>也看清钱花在了什么地方</em></h2><p>统计已由群主确认或归档的 AI 分账，小票商户、消费分类与地图地点保持同一份数据。</p></div><div className="finance-banner-total"><small>{financeMonthLabel(month)}群组消费</small><strong>{money(summary.current_total_cents)}</strong><span className={summary.change_percent > 0 ? 'up' : 'down'}>{changeText}</span></div></div>
    <div className="finance-filters"><label><span>月份</span><input type="month" value={month} onChange={event => setMonth(event.target.value)} /></label><label><span>群组</span><select value={groupId} onChange={event => setGroupId(event.target.value)}><option value="">全部群组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><label><span>消费分类</span><select value={category} onChange={event => setCategory(event.target.value)}><option value="">全部分类</option>{(data?.categories || []).map(name => <option key={name}>{name}</option>)}</select></label><button className="secondary-btn" onClick={load} disabled={loading}>{loading ? <LoaderCircle className="spin" size={14}/> : <TrendingUp size={14}/>}刷新分析</button></div>
    <div className="finance-kpis"><div><span>本月消费</span><strong>{money(summary.current_total_cents)}</strong><small>{summary.expense_count} 个商户消费记录</small></div><div><span>上月消费</span><strong>{money(summary.previous_total_cents)}</strong><small>{financeMonthLabel(data?.filters?.previous_month)}</small></div><div><span>区域变化</span><strong>{changeText}</strong><small>按当前筛选口径环比</small></div><div><span>地图覆盖</span><strong>{summary.coverage_percent}%</strong><small>{summary.located_count}/{summary.expense_count} 笔已标注</small></div></div>
    <div className="finance-grid">
      <div className="panel finance-map-panel"><div className="panel-head"><div><h3>群组消费热力图</h3><p>红色为本月，蓝色虚线为上月；圆点越大代表消费越高</p></div><MapPin size={18}/></div><FinancialMap current={data?.points?.current} previous={data?.points?.previous}/><div className="map-legend"><span><i className="current"/>本月</span><span><i className="previous"/>上月</span></div></div>
      <div className="panel group-heat-panel"><div className="panel-head"><div><h3>群组消费强度</h3><p>同一月份内各群组消费总额对比</p></div><Users size={18}/></div><div className="group-heat-list">{(data?.group_heatmap || []).map(row => <div key={row.group_id}><div><strong>{row.group_name}</strong><b>{money(row.current_cents)}</b></div><span><i style={{width:`${Math.max(0, row.intensity * 100)}%`}}/></span><small>上月 {money(row.previous_cents)}</small></div>)}{!data?.group_heatmap?.length && <div className="empty-state">暂无群组数据</div>}</div></div>
      <div className="panel category-heat-panel"><div className="panel-head"><div><h3>分类消费热力图</h3><p>按每月五个自然周展示分类消费强度</p></div><Layers3 size={18}/></div><div className="category-heat-table"><div className="category-heat-header"><span>分类</span>{[1,2,3,4,5].map(week => <b key={week}>W{week}</b>)}<b>合计</b></div>{(data?.category_heatmap || []).map(row => <div className="category-heat-row" key={row.category}><strong>{row.category}</strong>{row.weeks.map(cell => <span key={cell.week} style={{'--heat':cell.intensity}} title={`第 ${cell.week} 周 ${money(cell.amount_cents)}`}>{cell.amount_cents ? money(cell.amount_cents) : '-'}</span>)}<b>{money(row.total_cents)}</b></div>)}{!data?.category_heatmap?.length && <div className="empty-state">当前月份暂无分类消费</div>}</div></div>
      <div className="panel merchant-panel"><div className="panel-head"><div><h3>高消费商户排行</h3><p>按筛选范围内商户消费总额排序</p></div><Building2 size={18}/></div><div className="merchant-list">{(data?.merchant_ranking || []).map((row, index) => <div key={row.merchant}><span>{index + 1}</span><div><strong>{row.merchant}</strong><small>{row.group_names.join('、')} · {row.count} 笔</small><i><em style={{width:`${row.amount_cents / maxMerchant * 100}%`}}/></i></div><b>{money(row.amount_cents)}</b></div>)}{!data?.merchant_ranking?.length && <div className="empty-state">当前月份暂无商户消费</div>}</div></div>
      <div className="panel area-compare-panel"><div className="panel-head"><div><h3>本月与上月消费区域对比</h3><p>相近坐标合并为同一消费区域</p></div><TrendingUp size={18}/></div><div className="area-compare-list">{(data?.area_comparison || []).map(area => <div key={area.area_key}><div><strong>{area.name}</strong><small>{Number(area.lat).toFixed(3)}, {Number(area.lng).toFixed(3)}</small></div><span><small>上月</small><b>{money(area.previous_cents)}</b></span><span><small>本月</small><b>{money(area.current_cents)}</b></span><em className={area.change_percent > 0 ? 'up' : 'down'}>{area.change_percent === null ? '新增' : `${area.change_percent >= 0 ? '+' : ''}${area.change_percent}%`}</em></div>)}{!data?.area_comparison?.length && <div className="empty-state">补充消费地点后即可生成区域对比</div>}</div></div>
      <div className="panel unlocated-panel"><div className="panel-head"><div><h3>待标注消费地点</h3><p>补充地点后会立即进入热力图和区域对比</p></div><MapPin size={18}/></div><div className="unlocated-list">{(data?.unlocated || []).slice(0, 8).map(row => <div key={row.expense_id}><div><strong>{row.merchant}</strong><small>{row.group_name} · {row.spent_at} · {money(row.amount_cents)}</small></div><button className="secondary-btn" onClick={() => setEditingExpense(row)}><MapPin size={13}/>标注地点</button></div>)}{!data?.unlocated?.length && <div className="empty-state"><Check size={18}/>当前消费均已标注地点</div>}</div></div>
    </div>
    {editingExpense && <div className="modal-backdrop finance-location-backdrop" onMouseDown={event => event.target === event.currentTarget && setEditingExpense(null)}><div className="modal finance-location-modal"><ExpenseLocationEditor expense={editingExpense} notify={notify} onClose={() => setEditingExpense(null)} onSaved={async () => { setEditingExpense(null); await load() }}/></div></div>}
  </section>
}

function AuthScreen({ onAuth }) {
  const [mode, setMode] = useState('login')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('')
    const data = new FormData(event.currentTarget)
    try { await onAuth(mode, { username: data.get('username'), password: data.get('password'), nickname: data.get('nickname') || undefined }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy(false) }
  }
  return <div className="auth-page"><section className="auth-story"><div className="brand auth-brand"><div className="brand-mark"><Sparkles size={17} /></div><span>SyncMate</span></div><div className="auth-copy"><span className="label-chip"><Sparkles size={13} /> SMART SHARED LIFE</span><h1>共同生活，<br /><em>从此更合拍。</em></h1><p>把分账、群组与日程放在一个安静、清晰的空间里。</p></div><div className="auth-orbit"><div className="orbit orbit-one"/><div className="orbital-core"><Users size={30}/></div><span>账目清楚</span><span>时间合拍</span></div></section><section className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><span className="modal-kicker">{mode === 'login' ? 'WELCOME BACK' : 'JOIN SYNCMATE'}</span><h2>{mode === 'login' ? '登录你的空间' : '创建一个新账号'}</h2><p>{mode === 'login' ? '继续和伙伴们安排生活。' : '几秒钟后，就可以建立第一个群组。'}</p>{mode === 'register' && <label>昵称<div className="field-with-icon"><UserRound size={16}/><input name="nickname" required placeholder="怎么称呼你"/></div></label>}<label>用户名<div className="field-with-icon"><AtSign size={16}/><input name="username" required minLength="3" placeholder="请输入用户名" defaultValue={mode === 'login' ? 'demo' : ''}/></div></label><label>密码<div className="field-with-icon"><LockKeyhole size={16}/><input name="password" required minLength="6" type="password" placeholder="至少 6 位" defaultValue={mode === 'login' ? '123456' : ''}/></div></label>{error && <div className="form-error">{error}</div>}<button className="primary-btn auth-submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17}/> : mode === 'login' ? '登录' : '注册并进入'}<ArrowUpRight size={16}/></button><button type="button" className="auth-switch" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>{mode === 'login' ? '还没有账号？立即注册' : '已经有账号？返回登录'}</button><small className="demo-hint">演示账号：demo / 123456</small></form></section></div>
}

function ProfileModal({ user, onClose, onSaved, notify }) {
  const [section, setSection] = useState('profile')
  const [error, setError] = useState('')
  const saveProfile = async (event) => {
    event.preventDefault(); setError('')
    const data = new FormData(event.currentTarget)
    try { onSaved(await api('/me', { method: 'PATCH', body: JSON.stringify({ nickname: data.get('nickname'), avatar_color: data.get('avatar_color') }) })) }
    catch (requestError) { setError(requestError.message) }
  }
  const savePassword = async (event) => {
    event.preventDefault(); setError('')
    const data = new FormData(event.currentTarget)
    if (data.get('new_password') !== data.get('confirm_password')) return setError('两次输入的新密码不一致')
    try { await api('/me/password', { method: 'PATCH', body: JSON.stringify({ current_password: data.get('current_password'), new_password: data.get('new_password') }) }); onClose(); notify('密码修改成功') }
    catch (requestError) { setError(requestError.message) }
  }
  return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><div className="modal profile-modal"><button className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">PERSONAL SPACE</span><h2>个人设置</h2><div className="settings-tabs"><button className={section === 'profile' ? 'active' : ''} onClick={() => { setSection('profile'); setError('') }}><UserRound size={15}/>资料与头像</button><button className={section === 'password' ? 'active' : ''} onClick={() => { setSection('password'); setError('') }}><LockKeyhole size={15}/>修改密码</button></div>{section === 'profile' ? <form onSubmit={saveProfile}><div className="profile-preview"><Avatar initials={user.initials} large color={user.avatar_color}/><div><strong>{user.nickname}</strong><small>@{user.username}</small></div></div><label>昵称<input name="nickname" required defaultValue={user.nickname}/></label><label>头像配色<div className="color-options">{['rose','mint','violet','orange','blue'].map(color => <label className={`color-dot ${color}`} key={color}><input type="radio" name="avatar_color" value={color} defaultChecked={user.avatar_color === color}/><span/></label>)}</div></label>{error && <div className="form-error">{error}</div>}<button className="primary-btn settings-submit">保存资料</button></form> : <form onSubmit={savePassword}><label>当前密码<input name="current_password" type="password" required/></label><label>新密码<input name="new_password" type="password" minLength="6" required/></label><label>确认新密码<input name="confirm_password" type="password" minLength="6" required/></label>{error && <div className="form-error">{error}</div>}<button className="primary-btn settings-submit">更新密码</button></form>}</div></div>
}

export default App
