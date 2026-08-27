import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bell, CalendarDays, ChevronDown, CircleDollarSign, Grid2X2,
  LogOut, MoreHorizontal, Plus, Search, Settings, Sparkles, Users,
  WalletCards, X, ArrowUpRight, ArrowDownLeft, Check, UserRound,
  LockKeyhole, AtSign, LoaderCircle, Megaphone, Link2,
  UserPlus, Crown, PencilLine, ScrollText, Undo2, LogOutIcon, Trash2,
  Copy, CheckCircle2, XCircle, Palette
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { api, getToken, setToken } from './api'

const emptyDashboard = { stats: { expense: 0, income: 0, net: 0 }, pending_bills: [], pending_payments: [], transactions: [] }

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
  const pendingCount = dashboard.pending_bills.length + dashboard.pending_payments.length
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
        </nav>
        <div className="sidebar-bottom"><button onClick={() => setShowProfile(true)}><Settings size={18} />个人设置</button><button onClick={logout}><LogOut size={18} />退出登录</button></div>
      </aside>

      <main className="main-content">
        <header className="topbar"><div><p className="eyebrow">TUESDAY, AUGUST 26</p><h1>{tab === 'groups' ? '我的群组' : tab === 'calendar' ? '共享日程' : tab === 'wallet' ? '分账记录' : `早上好，${user.nickname}`}</h1></div><div className="top-actions"><label className="search"><Search size={16} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索群组、账单..." /></label><button className="icon-btn" onClick={() => notify(`${pendingCount} 件事项待处理`)}><Bell size={18} />{pendingCount > 0 && <i />}</button><button className="avatar-button" onClick={() => setShowProfile(true)}><Avatar initials={user.initials} color={user.avatar_color} /></button></div></header>

        {tab === 'overview' && <>
          <section className="hero-grid"><div className="hero-card"><div className="hero-copy"><span className="label-chip"><Sparkles size={13} /> 本月概览</span><h2>让每一次<br /><em>一起生活</em>都更轻松</h2><p>账目清楚了，时间对上了，<br />剩下的就是享受当下。</p><button className="primary-btn" onClick={() => setShowCreate(true)}>创建一个新群组 <ArrowUpRight size={16} /></button></div><div className="orbital"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbital-core"><CircleDollarSign size={32} /></div><span className="float-tag tag-a">¥ {dashboard.stats.income.toFixed(0)} <small>本月收入</small></span><span className="float-tag tag-b">{groups.length} 个群组</span></div></div><div className="stat-card"><div className="stat-top"><span>我的总支出</span><MoreHorizontal size={18} /></div><strong>¥ {displayExpense}</strong><span className="trend">收入 ¥{dashboard.stats.income.toFixed(2)} <small>{netSummary}</small></span><div className="mini-chart"><span style={{height:'32%'}}/><span style={{height:'46%'}}/><span style={{height:'38%'}}/><span style={{height:'66%'}}/><span style={{height:'54%'}}/><span className="hot" style={{height:'82%'}}/><span style={{height:'70%'}}/></div><div className="chart-labels"><small>W1</small><small>W2</small><small>W3</small><small>W4</small></div></div></section>
          <section className="section-head"><div><h3>最近的群组</h3><p>和重要的人，一起把生活安排好</p></div><button className="text-btn" onClick={() => setTab('groups')}>查看全部 <ArrowUpRight size={15} /></button></section>
          <section className="group-grid">{filteredGroups.slice(0, 3).map((group, index) => <GroupCard key={group.id} group={group} index={index} onClick={() => { setActiveGroup(group); setTab('groups') }} />)}<button className="add-card" onClick={() => setShowCreate(true)}><span><Plus size={21} /></span><strong>创建新群组</strong><small>从一次聚餐开始</small></button></section>
          <section className="bottom-grid"><div className="panel"><div className="panel-head"><div><h3>待处理事项</h3><p>{pendingCount} 件事项需要你的确认</p></div><button className="more-link" onClick={() => setTab('wallet')}>全部</button></div>{dashboard.pending_bills.map(item => <div className="todo" key={`bill-${item.id}`}><div className="todo-icon purple"><WalletCards size={17} /></div><div><strong>确认{item.title}账单</strong><small>{item.group_name} · ¥{Number(item.amount).toFixed(2)}</small></div><button onClick={() => notify('账单确认功能将在分账模块完成')}><Check size={16} /></button></div>)}{dashboard.pending_payments.map(item => <div className="todo" key={`payment-${item.id}`}><div className="todo-icon green"><CircleDollarSign size={17} /></div><div><strong>{item.status === 'pending_in' ? '待确认收款' : '待付款'}</strong><small>{item.group_name} · ¥{Number(item.amount).toFixed(2)}</small></div><button onClick={() => setTab('wallet')}><ArrowUpRight size={16} /></button></div>)}{pendingCount === 0 && <div className="empty-state"><Check size={20} />当前没有待处理事项</div>}</div><div className="panel"><div className="panel-head"><div><h3>最近动态</h3><p>你的个人收支记录</p></div><button className="more-link" onClick={() => setTab('wallet')}>全部</button></div>{recentTransactions.map((item, index) => <div className="transaction" key={`${item.title}-${index}`}><div className={`transaction-icon ${item.tone}`}><item.icon size={15} /></div><div><strong>{item.title}</strong><small>{item.sub}</small></div><b className={item.tone}>{item.amount}</b></div>)}</div></section>
        </>}

        {tab === 'groups' && <GroupsView groups={filteredGroups} activeGroup={activeGroup} setActiveGroup={setActiveGroup} onCreate={() => setShowCreate(true)} onJoin={() => setShowJoin(true)} notify={notify} refresh={loadData} user={user} />}
        {tab === 'calendar' && <CalendarView notify={notify} />}
        {tab === 'wallet' && <WalletView notify={notify} dashboard={dashboard} />}
      </main>
      {toast && <div className="toast"><Check size={16} />{toast}</div>}
      {showCreate && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setShowCreate(false)}><form className="modal" onSubmit={createGroup}><button type="button" className="modal-close" onClick={() => setShowCreate(false)}><X size={18} /></button><span className="modal-kicker">NEW CIRCLE</span><h2>创建一个新群组</h2><p>选择模板可以自动填入更适合该场景的公告与主题。</p><label>群组名称<input name="name" required placeholder="例如：周末聚餐" /></label><label>群组模板<select name="template_key"><option value="">自定义</option><option value="dorm">宿舍协同</option><option value="roommate">合租生活</option><option value="trip">结伴旅行</option><option value="dinner">聚餐活动</option></select></label><label>群组类型<select name="type"><option>好友</option><option>旅行</option><option>宿舍</option><option>合租</option><option>聚餐</option></select></label><button className="primary-btn" type="submit">创建群组 <ArrowUpRight size={16} /></button></form></div>}
      {showJoin && <JoinGroupModal initialCode={initialInviteCode} onClose={() => setShowJoin(false)} onJoined={async (message) => { setShowJoin(false); window.history.replaceState({}, '', '/'); await loadData(); notify(message) }} />}
      {showProfile && <ProfileModal user={user} onClose={() => setShowProfile(false)} onSaved={(next) => { setUser(next); setShowProfile(false); notify('个人资料已保存') }} notify={notify} />}
    </div>
  )
}

function GroupCard({ group, index, onClick }) { return <button className={`group-card ${group.color}`} onClick={onClick}><div className="card-top"><span className="group-type">{group.type}</span><MoreHorizontal size={18} /></div><div className="group-art"><div className="ring" /><span className="art-symbol">{index === 0 ? '✦' : index === 1 ? '◒' : '⌂'}</span></div><div className="card-info"><div><h4>{group.name}</h4><small><Users size={13} /> {group.people} 位成员</small></div><strong>{group.amount}</strong></div><div className="card-foot"><div className="avatar-stack">{group.members.map((m, i) => <Avatar key={m} initials={m} index={i} />)}</div><span>本月总额</span></div></button> }
function GroupsView({ groups, activeGroup, setActiveGroup, onCreate, onJoin, notify, refresh, user }) {
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
  const roleNames = { owner: '群主', admin: '管理员', member: '普通成员', temporary: '临时成员' }
  const canManage = ['owner', 'admin'].includes(detail?.current_role)
  if (!activeGroup) return <div className="empty-page"><Users size={30}/><h3>还没有群组</h3><p>创建群组或使用邀请码加入。</p><div><button className="primary-btn small" onClick={onCreate}>创建群组</button><button className="secondary-btn" onClick={onJoin}>邀请码加入</button></div></div>
  return <div className="group-manager">
    <aside className="group-rail"><div className="section-head compact"><div><h3>我的群组 <span className="muted-count">{groups.length}</span></h3><p>群组生活协同中心</p></div></div><div className="rail-actions"><button onClick={onCreate}><Plus size={15}/>新建</button><button onClick={onJoin}><Link2 size={15}/>加入</button></div><div className="groups-list">{groups.map((group, index) => <button className={`group-row ${activeGroup.id === group.id ? 'selected' : ''}`} key={group.id} onClick={() => { setActiveGroup(group); setView('overview') }}><div className={`row-art ${group.color}`}>{index === 0 ? '✦' : index === 1 ? '◒' : '⌂'}</div><div className="row-main"><strong>{group.name}</strong><small>{group.type} · {group.people} 位成员</small></div><b>{group.amount}</b></button>)}</div></aside>
    <section className="group-workspace">{!detail ? <div className="detail-loading"><LoaderCircle className="spin"/>加载群组资料</div> : <>
      <div className={`group-cover ${detail.theme_color} cover-${detail.cover_style}`}><div className="cover-copy"><span className="group-type">{detail.type}</span><h2>{detail.name}</h2><p>{detail.announcement || '还没有群公告，管理员可以在设置中添加。'}</p><div className="cover-meta"><span><Users size={14}/>{detail.people} 位成员</span><span><Crown size={14}/>{roleNames[detail.current_role]}</span><span><CircleDollarSign size={14}/>{detail.amount}</span></div></div><div className="cover-symbol"><Sparkles size={28}/></div></div>
      <div className="group-tabs"><button className={view === 'overview' ? 'active' : ''} onClick={() => setView('overview')}><Grid2X2 size={15}/>概览</button><button className={view === 'members' ? 'active' : ''} onClick={() => setView('members')}><Users size={15}/>成员</button><button className={view === 'invite' ? 'active' : ''} onClick={() => setView('invite')}><UserPlus size={15}/>邀请与审核{detail.join_requests.length > 0 && <b>{detail.join_requests.length}</b>}</button>{canManage && <button className={view === 'settings' ? 'active' : ''} onClick={() => setView('settings')}><Settings size={15}/>设置</button>}<button className={view === 'logs' ? 'active' : ''} onClick={() => setView('logs')}><ScrollText size={15}/>日志</button></div>
      {view === 'overview' && <GroupOverview detail={detail} setView={setView} notify={notify}/>} 
      {view === 'members' && <div className="manager-panel"><div className="manager-head"><div><h3>成员与权限</h3><p>成员备注、群内昵称、角色和加入时间</p></div><span>{detail.people} 人</span></div><div className="member-table">{detail.members_detail.map(member => <div className="member-record" key={member.id}><Avatar initials={member.initials} color={member.avatar_color}/><div className="member-identity"><strong>{member.display_name}</strong><small>@{member.username}{member.member_note ? ` · ${member.member_note}` : ''}</small></div><span className={`role-chip ${member.role}`}>{member.role === 'owner' && <Crown size={12}/>} {roleNames[member.role]}</span><time>{formatDate(member.joined_at)} 加入</time>{(canManage || member.id === user.id) && <button className="table-action" onClick={() => setEditingMember(member)}><PencilLine size={15}/></button>}</div>)}</div></div>}
      {view === 'invite' && <InvitePanel detail={detail} canManage={canManage} act={act} notify={notify}/>} 
      {view === 'settings' && canManage && <GroupSettings detail={detail} act={act} refresh={refresh}/>} 
      {view === 'logs' && <div className="manager-panel"><div className="manager-head"><div><h3>操作日志</h3><p>重要变更保留记录，部分操作支持撤销</p></div></div><div className="log-list">{detail.audit_logs.map(log => <div className="log-record" key={log.id}><div className="log-icon"><ScrollText size={15}/></div><div><strong>{log.summary}</strong><small>{log.actor} · {formatDate(log.created_at)}</small></div>{Boolean(log.undoable) && !log.undone && canManage && <button disabled={busy} onClick={() => act(() => api(`/groups/${detail.id}/logs/${log.id}/undo`, {method:'POST'}), '操作已撤销', true)}><Undo2 size={14}/>撤销</button>}{Boolean(log.undone) && <span>已撤销</span>}</div>)}</div></div>}
    </>}</section>
    {editingMember && <MemberModal member={editingMember} detail={detail} currentUser={user} onClose={() => setEditingMember(null)} onSave={async payload => { await act(() => api(`/groups/${detail.id}/members/${editingMember.id}`, {method:'PATCH', body:JSON.stringify(payload)}), '成员资料已更新'); setEditingMember(null) }} onRemove={async () => { await act(() => api(`/groups/${detail.id}/members/${editingMember.id}`, {method:'DELETE'}), '成员已移除', true); setEditingMember(null) }}/>} 
  </div>
}

function formatDate(value) { if (!value) return '-'; return new Date(value.replace(' ', 'T')).toLocaleDateString('zh-CN', {month:'short', day:'numeric'}) }
function GroupOverview({ detail, setView, notify }) { return <div className="overview-grid"><div className="manager-panel announcement-card"><div className="panel-icon mint"><Megaphone size={18}/></div><div><small>群公告</small><h3>{detail.announcement || '暂无群公告'}</h3><p>{detail.announcement ? '公告对所有群成员可见。' : '在群组设置中添加第一条公告。'}</p></div></div><div className="manager-panel metric-card"><small>成员构成</small><strong>{detail.people}</strong><p>{detail.members_detail.filter(m => m.role === 'admin').length} 位管理员 · {detail.members_detail.filter(m => m.role === 'temporary').length} 位临时成员</p><button onClick={() => setView('members')}>管理成员 <ArrowUpRight size={14}/></button></div><div className="manager-panel metric-card"><small>本期群组支出</small><strong>{detail.amount}</strong><p>所有账单均可追溯至付款人与参与成员</p><button onClick={() => notify('账单模块将在下一阶段完善')}>查看账单 <ArrowUpRight size={14}/></button></div><div className="manager-panel activity-card"><div className="manager-head"><div><h3>成员活跃度</h3><p>依据群组操作、管理与协作次数动态计算</p></div></div>{detail.members_detail.slice().sort((a,b) => b.activity_score-a.activity_score).slice(0,4).map(member => <div className="activity-row" key={member.id}><Avatar initials={member.initials} color={member.avatar_color}/><span>{member.display_name}</span><div><i style={{width:`${member.activity_score}%`}}/></div><b>{member.activity_score}</b></div>)}</div></div> }

function InvitePanel({ detail, canManage, act, notify }) { const joinLink=`${window.location.origin}/join/${detail.invite_code}`; return <div className="invite-grid"><div className="manager-panel invite-card"><div className="panel-icon blue"><Link2 size={18}/></div><h3>邀请成员</h3>{canManage ? <><p>邀请码将在 {formatDate(detail.invite_expires_at)} 失效，加入方式：{detail.join_requires_approval ? '需要审核' : '直接加入'}。</p><div className="qr-block"><QRCodeSVG value={joinLink} size={112} bgColor="#ffffff" fgColor="#403747" level="M"/><span>扫码打开入群申请</span></div><div className="invite-code"><strong>{detail.invite_code}</strong><button onClick={() => { navigator.clipboard?.writeText(detail.invite_code); notify('邀请码已复制') }}><Copy size={15}/></button></div><button className="secondary-btn" onClick={() => { navigator.clipboard?.writeText(joinLink); notify('邀请链接已复制') }}><Link2 size={14}/>复制邀请链接</button><button className="secondary-btn" onClick={() => act(() => api(`/groups/${detail.id}/invite`, {method:'POST', body:JSON.stringify({valid_days:7})}), '邀请已更新')}>生成新邀请</button></> : <p>只有群主和管理员可以查看或更新邀请。</p>}</div><div className="manager-panel request-card"><div className="manager-head"><div><h3>入群审核</h3><p>{canManage ? `${detail.join_requests.length} 条待处理申请` : '管理员可处理申请'}</p></div></div>{detail.join_requests.map(request => <div className="request-row" key={request.id}><Avatar initials={request.nickname.slice(-2)} color={request.avatar_color}/><div><strong>{request.nickname}</strong><small>@{request.username} · {formatDate(request.created_at)} 申请</small></div><button className="approve" onClick={() => act(() => api(`/groups/${detail.id}/requests/${request.id}/review`, {method:'POST',body:JSON.stringify({decision:'approved'})}), '已通过入群申请', true)}><CheckCircle2 size={16}/></button><button className="reject" onClick={() => act(() => api(`/groups/${detail.id}/requests/${request.id}/review`, {method:'POST',body:JSON.stringify({decision:'rejected'})}), '已拒绝入群申请')}><XCircle size={16}/></button></div>)}{detail.join_requests.length === 0 && <div className="empty-state"><Check size={18}/>当前没有待审核申请</div>}</div></div> }

function GroupSettings({ detail, act, refresh }) { const save = event => { event.preventDefault(); const data = new FormData(event.currentTarget); act(() => api(`/groups/${detail.id}`, {method:'PATCH',body:JSON.stringify({name:data.get('name'),type:data.get('type'),announcement:data.get('announcement'),theme_color:data.get('theme_color'),cover_style:data.get('cover_style'),join_requires_approval:data.get('approval') === 'on'})}), '群组设置已保存', true) }; return <div className="settings-grid"><form className="manager-panel group-settings-form" onSubmit={save}><div className="manager-head"><div><h3>群组资料与外观</h3><p>公告、主题和封面会同步给所有成员</p></div><Palette size={18}/></div><label>群组名称<input name="name" defaultValue={detail.name} required/></label><div className="form-row"><label>类型<select name="type" defaultValue={detail.type}><option>好友</option><option>旅行</option><option>宿舍</option><option>合租</option><option>聚餐</option></select></label><label>主题色<select name="theme_color" defaultValue={detail.theme_color}><option value="mint">薄荷绿</option><option value="lavender">雾紫</option><option value="peach">暖杏</option><option value="blue">浅蓝</option><option value="rose">柔粉</option></select></label></div><label>群公告<textarea name="announcement" defaultValue={detail.announcement} rows="3"/></label><label>封面样式<select name="cover_style" defaultValue={detail.cover_style}><option value="waves">流线</option><option value="grid">网格</option><option value="home">居家</option><option value="sun">日光</option></select></label><label className="toggle-line"><input type="checkbox" name="approval" defaultChecked={detail.join_requires_approval}/><span>新成员加入时需要管理员审核</span></label><button className="primary-btn small">保存设置</button></form><DangerZone detail={detail} act={act} refresh={refresh}/></div> }

function DangerZone({ detail, act }) { const [target, setTarget] = useState(''); const transferable = detail.members_detail.filter(m => !['owner','temporary'].includes(m.role)); return <div className="manager-panel danger-zone"><h3>成员关系与群组状态</h3><p>转让、退出和解散都是重要操作，请谨慎执行。</p>{detail.current_role === 'owner' && <><label>转让群主<select value={target} onChange={e => setTarget(e.target.value)}><option value="">选择新群主</option>{transferable.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label><button disabled={!target} onClick={() => act(() => api(`/groups/${detail.id}/transfer`, {method:'POST',body:JSON.stringify({new_owner_id:Number(target)})}), '群主已转让', true)}><Crown size={15}/>确认转让</button><button className="danger" onClick={() => window.confirm('确定解散该群组？解散后群组将不再显示。') && act(() => api(`/groups/${detail.id}`, {method:'DELETE'}), '群组已解散', true, false)}><Trash2 size={15}/>解散群组</button></>}{detail.current_role !== 'owner' && <button className="danger" onClick={() => window.confirm('确定退出该群组？') && act(() => api(`/groups/${detail.id}/leave`, {method:'POST'}), '已退出群组', true, false)}><LogOutIcon size={15}/>退出群组</button>}</div> }

function MemberModal({ member, detail, currentUser, onClose, onSave, onRemove }) { const submit = event => { event.preventDefault(); const data = new FormData(event.currentTarget); onSave({role:data.get('role') || null,group_nickname:data.get('group_nickname'),member_note:data.get('member_note')}) }; const isOwner = detail.current_role === 'owner'; const canManage = ['owner','admin'].includes(detail.current_role); return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}><form className="modal member-modal" onSubmit={submit}><button type="button" className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">MEMBER PROFILE</span><h2>成员资料</h2><div className="profile-preview"><Avatar initials={member.initials} color={member.avatar_color}/><div><strong>{member.display_name}</strong><small>@{member.username}</small></div></div><label>群内昵称<input name="group_nickname" defaultValue={member.group_nickname || ''} disabled={!canManage && member.id !== currentUser.id}/></label>{canManage && <label>成员备注<input name="member_note" defaultValue={member.member_note || ''} placeholder="仅群组管理员可见"/></label>}{isOwner && member.role !== 'owner' && member.id !== currentUser.id && <label>角色<select name="role" defaultValue={member.role}><option value="admin">管理员</option><option value="member">普通成员</option><option value="temporary">临时成员</option></select></label>}<button className="primary-btn">保存成员资料</button>{canManage && member.role !== 'owner' && member.id !== currentUser.id && <button type="button" className="remove-member" onClick={() => window.confirm(`确定移除 ${member.display_name}？`) && onRemove()}><Trash2 size={14}/>移出群组</button>}</form></div> }

function JoinGroupModal({ initialCode = '', onClose, onJoined }) { const [error,setError]=useState(''); const submit=async event=>{event.preventDefault();setError('');const code=new FormData(event.currentTarget).get('code');try{const result=await api('/groups/join',{method:'POST',body:JSON.stringify({invite_code:code})});onJoined(result.status==='pending'?`已申请加入“${result.group_name}”，等待审核`:`已加入“${result.group_name}”`)}catch(requestError){setError(requestError.message)}}; return <div className="modal-backdrop" onMouseDown={event => event.target===event.currentTarget&&onClose()}><form className="modal" onSubmit={submit}><button type="button" className="modal-close" onClick={onClose}><X size={18}/></button><span className="modal-kicker">JOIN A GROUP</span><h2>使用邀请码加入</h2><p>输入群管理员分享的 8 位邀请码。</p><label>邀请码<input name="code" required minLength="6" placeholder="例如：A1B2C3D4" defaultValue={initialCode}/></label>{error&&<div className="form-error">{error}</div>}<button className="primary-btn">申请加入 <ArrowUpRight size={16}/></button></form></div> }
function CalendarView({ notify }) { return <section className="calendar-page"><div className="calendar-banner"><div><span className="label-chip"><CalendarDays size={13} /> 本周安排</span><h2>找一个大家<br /><em>都方便的时刻</em></h2><p>已经收集到 4 位成员的空闲时间。</p></div><div className="calendar-orb">25<span>周日</span></div></div><div className="panel calendar-panel"><div className="panel-head"><div><h3>共同空闲时段</h3><p>根据成员投票与历史参与度推荐</p></div><button className="primary-btn small" onClick={() => notify('活动创建面板即将上线')}><Plus size={16} />创建活动</button></div><div className="time-slot recommended"><div><strong>周六 · 18:30 - 20:30</strong><small>6/6 人可参加 · 推荐指数 98%</small></div><span>最推荐</span><button onClick={() => notify('已选择周六 18:30')}>选择</button></div><div className="time-slot"><div><strong>周日 · 14:00 - 16:00</strong><small>5/6 人可参加 · 小林暂时冲突</small></div><span className="soft">备选</span><button onClick={() => notify('已选择周日 14:00')}>选择</button></div></div></section> }
function WalletView({ notify, dashboard }) { return <section className="wallet-page"><div className="wallet-hero"><div><span className="label-chip"><WalletCards size={13} /> 个人收支</span><h2>每一笔付出<br /><em>都有回应</em></h2><p>收入、支出与待确认款项，都清晰地记录在这里。</p></div><div className="wallet-number">¥ {dashboard.stats.expense.toFixed(2)}<small>累计支出 · 收入 ¥{dashboard.stats.income.toFixed(2)}</small></div></div><div className="panel"><div className="panel-head"><div><h3>待处理转账</h3><p>来自数据库的待付款和待确认收款</p></div><button className="text-btn" onClick={() => notify('数据已是最新状态')}>刷新状态 <Sparkles size={14} /></button></div>{dashboard.pending_payments.map((item, index) => <div className="payment-row" key={item.id}><Avatar initials={item.status === 'pending_in' ? 'IN' : 'OUT'} index={index} /><span>{item.status === 'pending_in' ? <><strong>{item.group_name}</strong> 有一笔款项待你确认</> : <>你需要完成 <strong>{item.group_name}</strong> 的付款</>}</span><b className={item.status === 'pending_in' ? 'positive' : ''}>¥ {Number(item.amount).toFixed(2)}</b><button onClick={() => notify(item.status === 'pending_in' ? '已发送确认提醒' : '付款确认将在分账模块完成')}><Check size={16} /></button></div>)}{dashboard.pending_payments.length === 0 && <div className="empty-state"><Check size={20} />所有款项均已确认</div>}</div></section> }

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
