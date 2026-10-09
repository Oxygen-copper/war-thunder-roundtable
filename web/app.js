'use strict';

let S = null;
let view = 'home', vtab = 'get', vcat = 'ground', convMode = 'sdv', ttsMode = 'manual';
let onlyMain = true, ttsEntries = [];
let pollTimer = null, logCursor = 0, curJob = null;
const LOG_MAX = 3000;          // 日志区最多留多少行，超出丢最老的
let avatarTab = 'avatars';
let curAvatarFiles = [];      // 当前分类的文件列表，卡片靠下标回查，避免字符串匹配出错

const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ------------------------------------------------ 基础 */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function toast(msg, kind) {
  const d = document.createElement('div');
  d.className = 'toast' + (kind ? ' ' + kind : '');
  d.textContent = msg; $('toasts').appendChild(d);
  setTimeout(() => d.remove(), 4500);
}
let logScrollQueued = false;
function logScrollEnd() {          // 一帧最多滚一次，别每行都逼浏览器重排
  if (logScrollQueued) return;
  logScrollQueued = true;
  requestAnimationFrame(() => {
    logScrollQueued = false;
    const el = $('log'); el.scrollTop = el.scrollHeight;
  });
}
function log(msg, kind) {
  const el = $('log');
  if (msg !== undefined) {
    const t = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    // 用文本节点追加是 O(1)。早先这里写的是 el.textContent += …，
    // 每加一行都要把整段日志重新拼一遍，解包那种上万行的输出会把页面卡死。
    el.appendChild(document.createTextNode(`[${t}] ${msg}\n`));
    while (el.childNodes.length > LOG_MAX) el.removeChild(el.firstChild);
    logScrollEnd();
  }
  if (kind === 'err') toast(msg, 'err');
}
async function get(u) { return await (await fetch(u)).json(); }
async function post(u, p) {
  return await (await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p || {}) })).json();
}
function mkb64(buf) {
  let bin = ''; const b = new Uint8Array(buf);
  for (let i = 0; i < b.length; i += 0x8000) bin += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return btoa(bin);
}

/* ------------------------------------------------ 悬停注释（延迟 0.8 秒） */

let tipTimer = null;
function bindTips() {
  document.addEventListener('mouseover', e => {
    const t = e.target.closest('[data-tip]');
    if (!t) return;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => {
      const tip = $('tip');
      tip.textContent = t.dataset.tip;
      tip.classList.add('show');
      const r = t.getBoundingClientRect();
      const w = tip.offsetWidth;
      tip.style.left = Math.max(10, Math.min(window.innerWidth - w - 12, r.left - w / 2 + r.width / 2)) + 'px';
      tip.style.top = (r.bottom + 9) + 'px';
    }, 800);
  });
  document.addEventListener('mouseout', e => {
    if (e.target.closest('[data-tip]')) {
      clearTimeout(tipTimer);
      $('tip').classList.remove('show');
    }
  });
  window.addEventListener('scroll', () => { clearTimeout(tipTimer); $('tip').classList.remove('show'); }, true);
}

/* ------------------------------------------------ 导航 */

const TAB_NAME = { get: '下载乘员组语音', conv: 'SDV换声 / TTS造声', build: '安装 / 打包' };
const CAT_NAME = { ground: '陆战乘员组', naval: '海战乘员组', air: '空战告警语音', common: '通用战场播报' };
const CONV_NAME = { sdv: 'SDV 换声', tts: 'TTS 造声' };

function setView(v) {
  view = v;
  $$('.view').forEach(s => s.classList.toggle('active', s.id === 'v-' + v));
  crumbs();
  if (v === 'voice') renderSources();
  if (v === 'avatar') renderAvatars();
}
function setVTab(t) {
  vtab = t;
  $$('#v-voice > .tabs .tab').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
  $$('#v-voice .pane').forEach(p => p.classList.toggle('active', p.id === 'p-' + t));
  crumbs();
}
function setCat(c) {
  vcat = c;
  $$('#v-voice .subtab').forEach(b => b.classList.toggle('active', b.dataset.cat === c));
  renderSources(); crumbs();
}
function setConv(m) {
  convMode = m;
  $$('#p-conv .sw').forEach(b => b.classList.toggle('active', b.dataset.conv === m));
  $$('#p-conv .convpane').forEach(p => p.classList.toggle('active', p.id === 'c-' + m));
  crumbs();
}
function crumbs() {
  const el = $('crumbs');
  const parts = [['首页', () => setView('home')]];
  if (view === 'voice') {
    parts.push(['语音包工程', () => setView('voice')]);
    parts.push([TAB_NAME[vtab], () => setVTab(vtab)]);
    if (vtab === 'get') parts.push([CAT_NAME[vcat], () => setCat(vcat)]);
    if (vtab === 'conv') parts.push([CONV_NAME[convMode], () => setConv(convMode)]);
  } else if (view === 'avatar') {
    parts.push(['战雷头像提取', () => setView('avatar')]);
  }
  el.innerHTML = parts.map((p, i) => {
    const last = i === parts.length - 1;
    return `${i ? '<span class="sep">/</span>' : ''}<button class="${last ? 'cur' : ''}" data-ci="${i}">${esc(p[0])}</button>`;
  }).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => parts[+b.dataset.ci][1]());
}

/* ------------------------------------------------ 模态框 / 目录浏览 */

function openModal(html, mount) {
  $('modalBox').innerHTML = html;
  $('modal').classList.add('show');
  $$('#modalBox [data-close]').forEach(b => b.onclick = closeModal);
  if (mount) mount($('modalBox'));
}
function closeModal() { $('modal').classList.remove('show'); $('modalBox').innerHTML = ''; }

function openBrowser(targetId, mode) {
  function paint(d) {
    const rows = [];
    if (d.parent) rows.push(`<div class="brow" data-nav="${esc(d.parent)}"><span>📁 ..</span><span class="muted">上一级</span></div>`);
    d.dirs.forEach(n => rows.push(`<div class="brow" data-nav="${esc(d.path + '\\' + n)}"><span>📁 ${esc(n)}</span><span class="muted">文件夹</span></div>`));
    d.files.forEach(f => rows.push(`<div class="brow" data-file="${esc(d.path + '\\' + f.name)}"><span>♪ ${esc(f.name)}</span><span class="muted">${f.mb} MB</span></div>`));
    $('modalBox').innerHTML = `
      <h3>${mode === 'file' ? '选一个文件' : '选一个文件夹'}</h3>
      <p class="sub">${mode === 'file'
        ? '点文件选中；也可以点进文件夹里找。'
        : (targetId === 'sdvSrc' || targetId === 'fxSrc'
          ? '进到目标文件夹，点「用这个文件夹」整批处理；只想试一条，就直接点下面那个文件。'
          : '进到目标文件夹，再点「用这个文件夹」。')}</p>
      <div class="shortcuts">${d.shortcuts.map(s => `<button class="btn tiny" data-nav="${esc(s[1])}">${esc(s[0])}</button>`).join('')}</div>
      <div class="browsebar"><input id="bPath" value="${esc(d.path)}"/><button class="btn tiny" id="bGo">前往</button></div>
      <div class="browse">${rows.join('') || '<div class="muted" style="padding:8px">（空）</div>'}</div>
      <div class="foot"><button class="btn" data-close>取消</button>
        ${mode === 'file' ? '' : '<button class="btn primary" id="bUse">用这个文件夹</button>'}</div>`;
    $$('#modalBox [data-nav]').forEach(e => e.onclick = () => load(e.dataset.nav));
    $$('#modalBox [data-file]').forEach(e => e.onclick = () => { $(targetId).value = e.dataset.file; closeModal(); });
    $('bGo').onclick = () => load($('bPath').value);
    if (mode !== 'file') $('bUse').onclick = () => { $(targetId).value = d.path; closeModal(); };
  }
  async function load(dir) {
    const r = await get('/api/browse?dir=' + encodeURIComponent(dir || ''));
    if (!r.ok) { toast(r.error || '打不开', 'err'); return; }
    paint(r);
  }
  load($('modalBox').dataset.lastDir || '');
  $('modal').classList.add('show');
}

/* ------------------------------------------------ 作业 */

let jobAfter = null;   // 作业成功完成后的收尾动作（例如「构建完问要不要装进游戏」）
function startJob(res, title, onDone) {
  if (!res.ok) { log('✗ ' + (res.error || '启动失败'), 'err'); return; }
  jobAfter = onDone || null;
  curJob = res.job; logCursor = 0;
  $('log').textContent = '';
  $('jobTitle').textContent = title || res.message || '作业';
  $('jobState').textContent = '运行中…';
  $('console').classList.remove('collapsed');
  log('▶ ' + (res.message || title || ''));
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollJob, 900); pollJob();
}
async function pollJob() {
  if (!curJob) return;
  const r = await get(`/api/job?id=${curJob}&from=${logCursor}`);
  if (!r.ok) return;
  (r.lines || []).forEach(l => log(l));
  logCursor = r.next;
  if (r.done) {
    clearInterval(pollTimer); pollTimer = null;
    $('jobState').textContent = (r.ok2 ? '✓ 完成 ' : '✗ 失败 ') + (r.elapsed != null ? r.elapsed + 's' : '');
    log(r.ok2 ? '✓ 作业完成' : '✗ 作业失败', r.ok2 ? null : 'err');
    await refresh();
    const after = jobAfter; jobAfter = null;
    if (r.ok2 && after) after();
  }
}

/* ------------------------------------------------ 语音：来源列表 */

function renderSources() {
  const V = S.voice;
  const meta = V.catMeta.find(c => c.id === vcat);
  $('catHint').textContent = meta ? meta.desc : '';
  let items = V.sources.filter(it => vcat === 'air' ? it.cat === 'vws' : it.cat === vcat);
  if (onlyMain) items = items.filter(i => i.main);
  $('srcGrid').innerHTML = items.length ? items.map(it => {
    const tag = (it.cat === 'vws' ? '<span class="tagx">全语种合一</span>' : '')
      + (it.alt ? '<span class="tagx">备用录音</span>' : '')
      + ((it.main && !it.alt) ? '<span class="tagx">八大系</span>' : '');
    return `<div class="lang${it.extracted ? ' done' : ''}${it.available ? '' : ' busy'}"
      data-cat="${esc(it.cat)}" data-code="${esc(it.code)}" title="${esc(it.bankName)}">
      <b>${esc(it.label)}${tag}</b>
      <small>${it.extracted ? `已解出 ${it.extracted} 条 · ${it.outMB} MB`
        : (it.available ? `未解包 · bank ${it.bankMB} MB` : '这个 bank 不在你的游戏里')}</small></div>`;
  }).join('') : '<p class="muted">这一类在你游戏里没有对应的 bank。</p>';
  $$('#srcGrid .lang').forEach(el => el.onclick = async () => {
    const cat = el.dataset.cat, code = el.dataset.code;
    if (!confirm(`解包「${el.querySelector('b').textContent}」的全部语音？\n（一次会解出几百到上千条 wav）`)) return;
    el.classList.add('busy');
    startJob(await post('/api/voice/extract', { cat, code }), '提取语音 ' + code);
  });
}

/* ------------------------------------------------ 语音：已安装 */

function renderMods() {
  const V = S.voice;
  const list = V.installed || [];
  if (!list.length) {
    $('modList').innerHTML = '<p class="muted tiny">还没有装任何语音包。装进来的东西放在 <code>游戏\\sound\\mod</code>，游戏启动时会加载它们。</p>';
    return;
  }
  // 按文件名里的语言代号分组，德系一堆、英系一堆，一眼能看出装了哪些国家的
  const groups = {};
  list.forEach(f => {
    const key = f.langLabel || '未识别';
    (groups[key] = groups[key] || []).push(f);
  });
  $('modList').innerHTML = Object.keys(groups).sort().map(g => `
    <div class="modgroup">
      <div class="modgroup-h"><b>${esc(g)}</b><span class="muted tiny">${groups[g].length} 个</span></div>
      ${groups[g].map(f => `
        <div class="modrow"><span>${esc(f.name)}</span>
          <span class="muted">${f.MB} MB · ${esc(f.mtime)}
          <button class="btn tiny" data-un="${esc(f.name)}">移除</button></span></div>`).join('')}
    </div>`).join('');
  $$('#modList [data-un]').forEach(b => b.onclick = async () => {
    if (!confirm('从游戏移除 ' + b.dataset.un + ' ?')) return;
    const r = await post('/api/voice/uninstall', { name: b.dataset.un });
    r.ok ? log('✓ ' + r.message) : log('✗ ' + r.error, 'err');
    await refresh();
  });
}

// 装之前先确认游戏开了模组支持；没开就问一句，然后代劳
async function installWithModCheck(src, names) {
  const V = (S || {}).voice || {};
  if (V.modEnabled === true) {
    startJob(await post('/api/voice/install', { src, names }), '安装到游戏');
    return;
  }
  const md = V.modDir || '游戏\\sound\\mod';
  openModal(`<button class="modal-x" data-close title="关闭">×</button>
    <h3>游戏还没打开语音模组支持</h3>
    <p class="sub">要装语音包，得先让游戏愿意加载 <code>sound\\mod</code> 里的东西。</p>
    <div class="gatebox">
      <div class="gtop"><b>我会做这两件事</b></div>
      <div class="gsub">1. 建好目录 <code>${esc(md)}</code>（不存在的话）<br/>
        2. 把游戏目录里 <code>config.blk</code> 的 <code>enable_mod</code> 改成 yes</div>
      <div class="gmiss">改之前会把 config.blk 备份成 <code>config.blk.bak-圆桌工程</code>，
        出问题直接改名换回来就行。除此之外不动 config.blk 的任何其他字节。</div>
    </div>
    <div class="foot">
      <button class="btn" data-close>先不装</button>
      <button class="btn primary" id="modFix">帮我改好并继续安装</button>
    </div>`,
    box => {
      const b = box.querySelector('#modFix');
      if (b) b.onclick = async () => {
        closeModal();
        const r = await post('/api/voice/prepare-mod', {});
        if (!r.ok) { toast(r.error || '处理失败', 'err'); return; }
        (r.steps || []).forEach(s => log('· ' + s));
        await refresh();
        startJob(await post('/api/voice/install', { src, names }), '安装到游戏');
      };
    });
}

/* ------------------------------------------------ TTS 稿子解析 */

// 与后端 parse_script 同一套规则：唯一分割点 = 每句开头的 WT + 四位数字
function parseScript(raw) {
  const out = [];
  String(raw || '').split(/(?=W\s*T\s*\d{4})/).forEach(piece => {
    const chunk = piece.trim();
    if (!chunk) return;
    const m = chunk.match(/^W\s*T\s*(\d{4})\s*[-–—－:：,，.、]?\s*([\s\S]*)$/);
    if (m) {
      const body = m[2].replace(/\s+/g, ' ').trim();
      if (body) out.push({ id: 'WT' + m[1], text: body });
    } else {
      const body = chunk.replace(/\s+/g, ' ').trim();
      if (body) out.push({ id: '', text: body });
    }
  });
  return out;
}

function renderTtsPreview() {
  $('ttsCount').textContent = ttsEntries.length + ' 条';
  if (!ttsEntries.length) {
    $('ttsPreview').innerHTML = '<div class="muted" style="padding:8px">还没有内容</div>';
    return;
  }
  const rows = ttsEntries.slice(0, 200).map((e, i) => {
    const id = e.id || String(i + 1).padStart(3, '0');
    return `<div class="pvrow"><span class="pvid">${esc(id)}</span><span class="pvtx">${esc(e.text)}</span></div>`;
  }).join('');
  const more = ttsEntries.length > 200
    ? `<div class="muted tiny" style="padding:6px">… 还有 ${ttsEntries.length - 200} 条</div>` : '';
  $('ttsPreview').innerHTML = rows + more;
}

/* ------------------------------------------------ 刷新 / 设置 */

async function refresh() {
  try {
    const r = await get('/api/state');
    if (!r.ok) throw new Error(r.error || '读取失败');
    S = r;
    const g = $('chipGame');
    g.textContent = r.voice.gameRoot ? '游戏：' + r.voice.gameRoot : '未找到游戏路径';
    g.className = 'chip ' + (r.voice.gameRoot ? 'ok' : 'bad');
    const t = r.voice.tools;
    $('chipTools').textContent = `vgmstream ${t.vgmstream ? '✓' : '✗'} · SDV ${t.sdv ? '✓' : '✗'} · TTS ${t.tts ? '✓' : '✗'} · FMOD ${t.fmodCli ? '✓' : '✗'}`;
    $('chipTools').className = 'chip ' + (t.vgmstream && t.sdv ? 'ok' : 'warn');
    const V = r.voice;
    if (!$('sdvSrc').value) $('sdvSrc').value = V.origRoot;
    if (!$('sdvDst').value) $('sdvDst').value = V.projRoot;
    if (!$('sdvRef').value) $('sdvRef').value = V.refRoot;
    if (!$('ttsRef').value) $('ttsRef').value = V.refRoot;
    if (!$('ttsDst').value) $('ttsDst').value = V.projRoot;
    if (!$('fxDst').value) $('fxDst').value = V.packRoot;
    renderSources(); renderMods(); crumbs();
    renderAvatars();
  } catch (e) { toast('读取状态失败：' + e.message, 'err'); }
}

function openSettings() {
  const c = S ? S.config : {};
  const f = (id, label, key) => `<div class="field"><label>${label}</label><input id="${id}" value="${esc(c[key] || '')}"/></div>`;
  openModal(`<h3>设置</h3><p class="sub">换电脑或给别人用时，把这几个路径填对就行</p>
    ${f('cfgGame', '游戏根目录（里面有 sound 目录）', 'game_root')}
    ${f('cfgSdv', 'SeedVC 目录', 'sdv_root')}
    ${f('cfgTts', 'IndexTTS2 目录', 'tts_root')}
    ${f('cfgUvr', 'UVR5 目录', 'uvr_root')}
    ${f('cfgFmod', 'FMOD 模组包目录（含 .fspro）', 'fmod_kit')}
    <p class="sub">留空会自动搜索常见位置。</p>
    <div class="foot"><button class="btn" data-close>取消</button><button class="btn primary" id="cfgGo">保存</button></div>`,
    box => box.querySelector('#cfgGo').onclick = async () => {
      const p = {
        game_root: box.querySelector('#cfgGame').value,
        sdv_root: box.querySelector('#cfgSdv').value, tts_root: box.querySelector('#cfgTts').value,
        uvr_root: box.querySelector('#cfgUvr').value, fmod_kit: box.querySelector('#cfgFmod').value,
      };
      closeModal();
      const r = await post('/api/config', p);
      r.ok ? log('✓ ' + r.message) : log('✗ ' + r.error, 'err');
      await refresh();
    });
}

/* ------------------------------------------------ 导入 */

async function installFromZip(file) {
  const zipb64 = mkb64(await file.arrayBuffer());
  const r0 = await post('/api/voice/import', { zipb64, name: file.name.replace(/\.zip$/i, '') });
  if (!r0.ok) return log('✗ ' + r0.error, 'err');
  log('✓ ' + r0.message);
  installWithModCheck(r0.path);
}

/* ------------------------------------------------ 声明 / 门禁检测 */

function openNotice() {
  openModal(`<h3>声明</h3>
    <div class="noticebox">
      <p>本工具是《战争雷霆》玩家自制的<b>模组辅助工具</b>，只做三件事：</p>
      <ol>
        <li>从<b>你本机</b>的游戏文件里提取语音 / 头像素材</li>
        <li>把素材加工成语音包</li>
        <li>把成品装回<b>你本机</b>的游戏目录</li>
      </ol>
      <p>不提供任何游戏本体资源下载，不绕过反作弊，不修改游戏内存，<b>不联网上传任何数据</b>。</p>
      <p>提取出来的素材版权归 <b>Gaijin Entertainment</b> 所有，仅供<b>个人学习与娱乐</b>使用，
         请勿用于商业用途，也不要二次分发原始素材。</p>
      <p>语音合成用到的第三方模型各有自己的许可：</p>
      <ul>
        <li><b>SeedVC</b> —— GPL-3.0（可自由再分发，但具传染性）</li>
        <li><b>IndexTTS2</b> —— 《bilibili 模型使用许可协议》。该协议 <b>4.2 条明确禁止</b>
            用于医疗、自动驾驶、<b>军事</b>、关键基础设施等高风险场景。本工具仅用于
            <b>游戏模组制作与个人娱乐</b>，不做任何现实用途。</li>
      </ul>
      <p>用本工具生成的语音包，请自行确认是否违反游戏用户协议；
         作者不对封号、纠纷等后果负责。</p>
    </div>
    <div class="foot"><button class="btn primary" data-close>我知道了</button></div>`);
}

function openDownload(title, kind) {
  const v0 = (S.env || {}).voice || {};
  const isFmod = kind === 'fmod';
  const fmodKit = (((S || {}).voice || {}).tools || {}).fmodKit || '';
  const want = isFmod ? (fmodKit || 'D:\\战雷语音包\\fmod_studio_warthunder_for_modders-master')
                      : ((kind === 'sdv' ? v0.sdv : v0.tts) || {}).want || '';
  const items = kind === 'sdv' ? [
    ['SeedVC 官方仓库（GPL-3.0）', 'https://github.com/Plachtaa/seed-vc'],
    ['模型权重 HuggingFace（国内可加 hf-mirror 前缀）', 'https://huggingface.co/Plachta/Seed-VC'],
    ['国内镜像：魔搭 ModelScope 搜 seed-vc', 'https://www.modelscope.cn/models'],
  ] : isFmod ? [
    ['FMOD Studio 官方下载（免费版就够，不用买商业授权）', 'https://www.fmod.com/download'],
    ['战雷模组维基（找官方模组工具包）', 'https://wiki.warthunder.com/Modding'],
  ] : [
    ['IndexTTS2 官方仓库', 'https://github.com/index-tts/index-tts'],
    ['模型权重 HuggingFace（国内可加 hf-mirror 前缀）', 'https://huggingface.co/IndexTeam/IndexTTS-2'],
    ['国内镜像：魔搭 ModelScope 搜 IndexTTS-2', 'https://www.modelscope.cn/models'],
  ];
  openModal(`<h3>${esc(title)} · 下载</h3>
    <p class="sub">${isFmod ? 'FMOD 与战雷模组工具包各有自己的许可，不随主程序分发 —— 请从原始出处获取。'
                            : '扩展包体积很大、而且各有自己的许可，所以不随主程序分发 —— 请从原始出处获取。'}</p>
    <div class="noticebox">
      <ul>${items.map(i => `<li><a href="${i[1]}" target="_blank">${esc(i[0])}</a></li>`).join('')}</ul>
      <p><b>放哪里：</b>把解压出来的整个文件夹放到 <code>${esc(want)}</code>，
         或者在右上角「设置」里把路径指到它。回来自动就能检测通过。</p>
      ${isFmod ? '<p class="tiny muted">模组包里带一个 <code>FMOD Studio 2.02.22</code> 目录，命令行就在里面，工程会自动找到它。</p>' : ''}
      <p class="tiny muted">一键自动安装器还在做，先用上面的官方渠道。</p>
    </div>
    <div class="foot"><button class="btn primary" data-close>好</button></div>`);
}

function openOtherTts() {
  const list = ((S.env || {}).voice || {}).otherTts || [];
  openModal(`<h3>我想做其他语言的造声</h3>
    <p class="sub">IndexTTS2 只会中 / 英（日、西待验证）。要造德语、俄语、法语这些，请换下面这些项目 ——
      它们都支持多语种，而且各自有明确的许可。</p>
    ${list.map(t => `<div class="ttscard">
       <div class="ttscard-h"><b>${esc(t.name)}</b><span class="lic">${esc(t.license)}</span></div>
       <p>${esc(t.why)}</p>
       <a class="btn tiny" href="${t.url}" target="_blank">打开项目页</a>
     </div>`).join('')}
    <div class="foot"><button class="btn primary" data-close>知道了</button></div>`);
}

/* ------------------------------------------------ 语音：打包前分析素材 */

function renderScan(res) {
  const slots = (S.voice && S.voice.kitSlots) || [];
  const best = res.best || null;
  const opts = slots.map(s => {
    const sel = best && s.root === best.root && s.lang === best.lang ? ' selected' : '';
    return `<option value="${esc(s.root)}||${esc(s.lang)}"${sel}>` +
      `${esc(s.rootLabel)} · ${esc(s.langLabel)}（工程 ${s.total} 条）</option>`;
  }).join('');
  const isUk = best && best.root === 'dialogs_wt_tanks_2023' && best.lang === 'english_uk';
  const bad = res.unmatchedCount || 0;
  $('scanOut').innerHTML = `
    <div class="scanres">
      <p class="big">这套素材共 <b>${res.files}</b> 条音频；按选中的槽位整理，能对上
        <span class="n">${res.matched}</span> 条${bad ? `，另有 <span class="k">${bad}</span> 条认不出来` : ''}。</p>
      ${best ? `<p class="tiny muted">推测目标：${esc(best.rootLabel)} · ${esc(best.langLabel)}
        ${(res.hintLanguages || []).includes(best.lang) ? '（从文件夹名就能看出来）' : '（按文件名命中数量猜的，不对请手动改）'}。
        换一个槽位也可以 —— 比如你拿中文音频，就是要顶掉英语车组的位置。</p>`
        : '<p class="tiny muted">没能自动判断目标槽位，请在下面手动选一个。</p>'}
      <div class="field"><label>要替换哪个槽位</label>
        <select id="slotPick" class="mini">${opts}</select></div>
      ${bad ? `<p class="tiny muted">认不出的那些不会写进工程，可以直接不管。例如：${esc((res.unmatched || []).slice(0, 4).join('、'))}</p>` : ''}
      ${isUk ? `<div class="tutbody"><div class="warnbox">这是英系车组。游戏里英国车还用到
        <b>en_au（澳洲）</b>和 <b>en_za（南非）</b>两个语音包，但官方工程里没有这两个槽位的素材 ——
        所以它们没法直接构建。只做 en 的话，开澳洲车、南非车听到的还是原版语音。</div></div>` : ''}
      <div class="row">
        <button class="btn primary" id="packGo">按这个槽位整理并构建 bank</button>
      </div>
    </div>`;
  $('packGo').onclick = async () => {
    const v = $('slotPick').value.split('||');
    startJob(await post('/api/voice/pack', {
      src: $('fmodSrc').value, root: v[0], lang: v[1]
    }), '整理素材并构建 bank', askInstallAfterBuild);
  };
}

// bank 构建完成之后问一句：要不要顺手装进游戏
function askInstallAfterBuild() {
  const dir = ((S || {}).voice || {}).packRoot || '';
  openModal(`<button class="modal-x" data-close title="关闭">×</button>
    <h3>bank 构建完成</h3>
    <p class="sub">产物已经收在下面这个目录里。</p>
    <div class="gatebox soft">
      <div class="gpath">${esc(dir || '（未知目录）')}</div>
    </div>
    <div class="gatebox">
      <div class="gtop"><b>要顺手装进游戏吗？</b></div>
      <div class="gsub">装到 <code>游戏\\sound\\mod</code>，重启游戏生效。
        <b>装之前会自动备份</b>被覆盖的文件；页面上那个「清空 sound\\mod」随时是你的退路。</div>
    </div>
    <div class="foot">
      <button class="btn" data-close>先不装，我自己留着</button>
      <button class="btn primary" id="packInstall">装进游戏</button>
    </div>`,
    box => {
      const b = box.querySelector('#packInstall');
      if (b) b.onclick = async () => {
        closeModal();
        setVTab('build');
        installWithModCheck(dir);
      };
    });
}

/* ------------------------------------------------ 语音：新手三页说明 */

const TUT_TITLES = ['下载原版语音', 'SDV / TTS', '打包'];
let tutPage = 0;

// 每个下载渠道都写清"适合什么情况"，不然新手只会看到一堆链接
function tutChannel(bold, url, why) {
  return `<div class="dlrow"><b><a href="${url}" target="_blank">${esc(bold)}</a></b>
    <span class="why">${why}</span></div>`;
}

function tutDlBlock(sdvOk, ttsOk, gpuOk, fmodOk) {
  let h = '';
  if (!sdvOk) {
    h += '<h4>SDV 换声 · 从哪个渠道拿</h4>'
      + tutChannel('点这里跳转到 SeedVC 官方仓库下载', 'https://github.com/Plachta/seed-vc',
          '适合：能正常打开 GitHub 的人。工具本体和安装说明都在这儿，照着做最稳。')
      + tutChannel('点这里跳转到 HuggingFace 下载模型权重', 'https://huggingface.co/Plachta/Seed-VC',
          '适合：单独补模型文件。国内直连经常失败，挂着梯子时用这个。')
      + tutChannel('点这里跳转到 hf-mirror 国内镜像下载', 'https://hf-mirror.com/Plachta/Seed-VC',
          '适合：HuggingFace 打不开的时候。内容一样，只是换了个连得上的地址。')
      + tutChannel('点这里跳转到魔搭 ModelScope 搜索', 'https://www.modelscope.cn/models',
          '适合：完全不想挂梯子。进去搜 “SeedVC” 找对应模型。');
  }
  if (!ttsOk) {
    h += '<h4>TTS 造声 · 从哪个渠道拿</h4>'
      + tutChannel('点这里跳转到 IndexTTS2 官方仓库下载', 'https://github.com/index-tts/index-tts',
          '适合：能正常打开 GitHub 的人。工具本体和说明都在这儿。')
      + tutChannel('点这里跳转到 HuggingFace 下载模型权重', 'https://huggingface.co/IndexTeam/IndexTTS-2',
          '适合：单独补模型文件。国内直连经常失败，挂着梯子时用这个。')
      + tutChannel('点这里跳转到 hf-mirror 国内镜像下载', 'https://hf-mirror.com/IndexTeam/IndexTTS-2',
          '适合：HuggingFace 打不开的时候。')
      + tutChannel('点这里跳转到魔搭 ModelScope 搜索', 'https://www.modelscope.cn/models',
          '适合：完全不想挂梯子。进去搜 “IndexTTS” 找对应模型。');
  }
  if (!gpuOk) {
    h += '<h4>显卡驱动 · 从哪个渠道拿</h4>'
      + tutChannel('点这里跳转到 NVIDIA 官方驱动下载', 'https://www.nvidia.cn/geforce/drivers/',
          '适合：驱动太旧或者没装。这是安装程序，下载后要自己点下一步，装完建议重启一次电脑。')
      + tutChannel('点这里跳转到按显卡型号查驱动', 'https://www.nvidia.cn/download/index.aspx',
          '适合：不确定该装哪个版本的时候，按显卡型号和系统选。');
  }
  if (fmodOk === false) {
    h += '<h4>FMOD Studio · 打包成 bank 要用</h4>'
      + tutChannel('点这里跳转到 FMOD 官方下载页', 'https://www.fmod.com/download',
          '适合：还没装 FMOD。打包模组只需要免费的 FMOD Studio，不用买商业授权。')
      + tutChannel('点这里跳转到战雷模组维基', 'https://wiki.warthunder.com/Modding',
          '适合：要那个带 .fspro 的模组工程。官方模组工具包叫 fmod_studio_warthunder_for_modders，从这里顺着找。');
  }
  if (h) {
    h += `<div class="okbox">下载完放哪儿：把解压出来的整个文件夹放进
      <code>扩展\\SDV\\</code> 或 <code>扩展\\TTS\\</code>，或者到右上角「设置」里把路径指过去。
      FMOD 模组包放进 <code>战雷语音包\\</code>，再在「设置」里把 FMOD 路径指到它。
      放好回来点一次「刷新」，上面的检测就会变成已装好。</div>`;
  }
  return h;
}

function tutPage1() {
  const V = ((S || {}).voice) || {};
  const gs = V.gameSlots || {};
  const ks = V.kitSlots || [];
  const kitOf = root => ks.filter(s => s.root === root).map(s => s.langLabel).join(' · ');
  const groundNames = (gs.ground || []).map(x => x.label).join('、');
  const nGround = (gs.ground || []).length, nNaval = (gs.naval || []).length, nCommon = (gs.common || []).length;
  return `
  <p>做语音包的第一步：先把游戏自带的乘员语音<b>解包</b>出来，它就是后面要加工的原料。</p>

  <h4>先弄清一件事：换声只换嗓子，不换说什么</h4>
  <p>换声工具（SDV）是<b>换音色</b>，不是造新话。原来那句是英文，换完还是英文，只是嗓子变成了另一个人的。所以：</p>
  <ul>
    <li>拿中文音色去换英文语音，出来是<b>英文发音</b>，不会带中文口音；</li>
    <li>但两边语言差得越远，<b>换出来的音色会没那么像</b>。想效果最好，参考音色尽量用和目标一样的语言。</li>
  </ul>

  <h4>关于语言：游戏支持得很多，官方工程只带了一部分</h4>
  <p>这两件事必须分开看，不然很容易误判 —— 下面左边一列是工具从你游戏里扫出来的，右边一列是官方 FMOD 工程里带的：</p>
  <table class="langtbl">
    <tr><th>类别</th><th>游戏本体支持</th><th>官方工程自带素材</th></tr>
    <tr><td>陆战乘员组</td>
        <td>${nGround || 29} 种${groundNames ? `<br/><span class="tiny muted">${esc(groundNames)}</span>` : ''}</td>
        <td>${kitOf('dialogs_wt_tanks_2023') || '英国 · 美国 · 德国 · 苏联/俄罗斯'}</td></tr>
    <tr><td>海战乘员组</td><td>${nNaval || 7} 种</td>
        <td>${kitOf('dialogs_wt_ships_2022') || '英 · 美 · 德 · 法 · 意 · 日 · 俄'}</td></tr>
    <tr><td>战场播报</td><td>${nCommon || 17} 种（含中文、日语）</td>
        <td>${kitOf('dialogs_wopl') || '英语 · 德语 · 俄语'}</td></tr>
    <tr><td>空战告警</td><td>英 / 日 / 中 三套</td><td>三套都带</td></tr>
  </table>
  <p><b>中系车本来就是中文乘员语音，游戏完全支持。</b>缺的是官方工程里没有中文车组的素材和事件，
     所以没法用它直接构建出 <code>_crew_dialogs_ground_zh</code> 这个 bank —— 是工程没带，不是游戏做不到。</p>

  <h4>想做中文 / 日文这类语音包，两条路</h4>
  <ol>
    <li><b>借槽位（流程能完整跑通）</b>：拿英 / 美 / 德 / 俄的槽位做，音频照它们的路径放。
        得到的是「这几个国家的车组说中文」，它<b>不会</b>替换中系车组的语音。</li>
    <li><b>补建对应语言</b>：给工程补上中文车组的素材与事件，再构建中系 bank。工作量大得多，
        官方工程里没有现成结构可以照抄。</li>
  </ol>

  <div class="warnbox">英系车组还有个附带情况：游戏里英国车用到 <b>en / en_au / en_za</b> 三个 bank
    （英国、澳洲、南非），官方工程只带 en 一个。只做 en 的话，开澳洲车、南非车听到的还是原版语音。</div>

  <h4>第一次做，建议</h4>
  <p>从英、美、德、俄里挑一个陆战车组，这四个能一路跑通全流程，先熟悉一遍再说。</p>

  <h4>现在动手</h4>
  <ol>
    <li>关掉这个窗口，到「① 下载乘员组语音」；</li>
    <li>选「陆战乘员组」，挑一个语种方格点一下；</li>
    <li>确认之后它会解出几百条 wav，放到 <code>语音\\原版\\</code> 下。</li>
  </ol>`;
}

function tutPage2() {
  const v = (S.env || {}).voice || {};
  const sdv = v.sdv || {}, tts = v.tts || {}, gpu = v.gpu || {};
  const tk = ((S || {}).voice || {}).tools || {};
  const fmodOk = !!tk.fmodCli && !!tk.fmodProject;
  const miss = [];
  if (!sdv.ok) miss.push('SDV 换声');
  if (!tts.ok) miss.push('TTS 造声');
  if (!gpu.ok) miss.push('显卡驱动环境');
  if (!fmodOk) miss.push('FMOD（打包用）');
  const badge = ok => ok ? '<span class="gb ok">✓ 已装好</span>' : '<span class="gb warn">✗ 没检测到</span>';

  let head = '';
  if (miss.length) {
    head = `<div class="warnbox">
      <b>检测到你这台电脑还缺：${esc(miss.join('、'))}</b><br/>
      ${!sdv.ok ? 'SDV 是语音包制作的<b>核心</b>工具 —— 没有它，就没法把原版语音换成目标音色。<br/>' : ''}
      ${!tts.ok ? 'TTS 是语音包制作的<b>重要</b>工具 —— 想造原版里没有的台词时才用它，不做这类可以暂时不装。<br/>' : ''}
      ${!gpu.ok ? '没有显卡驱动环境，SDV 和 TTS 都跑不起来。<br/>' : ''}
      ${!fmodOk ? 'FMOD 是把音频打成 <code>.bank</code> 的那一步，<b>工程会自己调它</b>，你只需要装上。<br/>' : ''}
    </div>` + tutDlBlock(sdv.ok, tts.ok, gpu.ok, fmodOk);
  } else {
    head = `<div class="okbox">这台电脑上的 SDV、TTS、显卡驱动和 FMOD 都已经就位，可以一路跑到打包。
      ${gpu.name ? '（显卡：' + esc(gpu.name) + '，驱动 ' + esc(gpu.driver) + '）' : ''}</div>`;
  }

  return `${head}
  <p>两个工具用途不一样，用哪个取决你要做什么。</p>
  <div class="gatebox">
    <div class="gtop"><b>SDV 换声</b>${badge(sdv.ok)}</div>
    <div class="gsub">把已经有的语音换成另一个人的音色。不改变原话说的是什么，只换嗓子。</div>
    <div class="gpath">约 ${esc(String(sdv.sizeGB || 9))} GB · 需要 ${esc(sdv.vram || '')} 显存 · 装在 ${esc(sdv.root || '（未配置）')}</div>
  </div>
  <div class="gatebox">
    <div class="gtop"><b>TTS 造声</b>${badge(tts.ok)}</div>
    <div class="gsub">直接用文字生成语音。想造原版里没有的台词、或者自己编台词时用它。</div>
    <div class="gpath">约 ${esc(String(tts.sizeGB || 19))} GB · 需要 ${esc(tts.vram || '')} 显存 · 装在 ${esc(tts.root || '（未配置）')}</div>
  </div>

  <h4>怎么选</h4>
  <ul>
    <li>把游戏原版台词换成别的音色 → 用 <b>SDV</b>；</li>
    <li>想说原版里根本没有的台词 → 用 <b>TTS</b>。</li>
  </ul>

  <h4>怎么用</h4>
  <ol>
    <li><b>SDV</b>：到「② SDV换声」。源＝<code>语音\\原版\\</code> 里刚解出来的那个文件夹；参考＝目标音色的一段干净人声
        （5–15 秒最合适，别带伴奏和混响）；输出＝一个新文件夹。迭代步数先用 30。</li>
    <li><b>TTS</b>：到「② TTS造声」。可以直接打台词，也可以传 TXT（每句用 <code>WT0001-</code> 这样的编号开头分句），
        选好参考音色和情绪参考再生成。</li>
  </ol>
  <div class="warnbox">参考音色的质量直接决定成品。宁可多花十分钟挑一段干净的，也别拿带伴奏、带和声的素材凑合。</div>`;
}

function tutPage3() {
  return `
  <p>这里只有一个入口 —— <b>把东西给我</b>，剩下的我来判断。</p>

  <h4>它会自动做这几步</h4>
  <ol>
    <li>先看你给的是 <code>.bank</code> 还是音频素材（<code>.wav</code> 等）；</li>
    <li>音频的话，逐个比对官方工程里每条音频<b>该放的位置</b>，自动归位 ——
        文件夹叫中文（比如「指挥官」）、分类混在一起、带了多余前缀，都能认出来；</li>
    <li>实在认不出的会<b>列出来让你确认</b>，不瞎猜；</li>
    <li>然后调 FMOD 构建 bank，收集到「成品」，最后装进游戏的 <code>sound\\mod</code>。</li>
  </ol>

  <h4>英系车组要留意</h4>
  <p>游戏里英国车组用到 <b>en / en_au / en_za</b> 三个 bank（英国、澳洲、南非），官方工程只带 en 一个。
     如果你的包里只有 en，我会提醒你 —— 但请注意：<b>官方工程里没有 en_au / en_za 这两个槽位的素材和事件，
     所以工程没法替你构建它们</b>。这两个要自己补素材才能做，做了才会生效。</p>

  <div class="warnbox">装进游戏之前，工具会自动备份 <code>sound\\mod</code> 里被覆盖的东西；
    页面上那个「清空 sound\\mod」随时是你的退路。</div>

  <h4>动手</h4>
  <p>关掉窗口，到「③ 安装 / 打包」，把素材文件夹（或者做好的 bank、打包好的 zip）交给它就行。</p>`;
}

function openVoiceTut(page) {
  tutPage = Math.max(0, Math.min(TUT_TITLES.length - 1, page | 0));
  const bodies = [tutPage1(), tutPage2(), tutPage3()];
  openModal(`<button class="modal-x" data-close title="关闭">×</button>
    <h3>新手三页：从下载到装进游戏</h3>
    <p class="sub">第 ${tutPage + 1} / ${TUT_TITLES.length} 页 · ${esc(TUT_TITLES[tutPage])}
       —— 已经有经验的话，直接关掉即可，不影响任何功能。</p>
    ${bodies.map((b, i) => `<div class="tutpage${i === tutPage ? ' active' : ''}" data-p="${i}">
      <div class="tutbody">${b}</div></div>`).join('')}
    <div class="tutnav">
      <button class="btn" id="tutPrev" ${tutPage === 0 ? 'disabled' : ''}>上一页</button>
      <button class="btn primary" id="tutNext">${tutPage === TUT_TITLES.length - 1 ? '看完了，开始' : '下一页'}</button>
      <span class="dots">${TUT_TITLES.map((_, i) =>
        `<span class="dot${i === tutPage ? ' on' : ''}"></span>`).join('')}</span>
    </div>`,
    box => {
      const prev = box.querySelector('#tutPrev'), next = box.querySelector('#tutNext');
      prev.onclick = () => openVoiceTut(tutPage - 1);
      next.onclick = () => {
        if (tutPage === TUT_TITLES.length - 1) { closeModal(); setView('voice'); return; }
        openVoiceTut(tutPage + 1);
      };
    });
}

function openVoiceGate() {
  const v = (S.env || {}).voice || {};
  const sdv = v.sdv || {}, tts = v.tts || {}, sh = v.shared || {}, tl = v.ttsLang || {};
  const tk = ((S || {}).voice || {}).tools || {};
  const fmodCli = tk.fmodCli || '', fmodProj = tk.fmodProject || '', fmodKit = tk.fmodKit || '';
  const fmodOk = !!fmodCli && !!fmodProj;
  const badge = ok => ok ? '<span class="gb ok">✓ 已检测到</span>' : '<span class="gb bad">✗ 未检测到</span>';
  const miss = o => {
    const m = [];
    if (!o.hasPython) m.push('Python 运行库');
    if (!o.hasCode) m.push('程序代码');
    if (!o.hasModel) m.push('模型权重');
    return m.length ? '缺少：' + m.join('、') : '';
  };
  openModal(`<h3>语音包工程 · 环境检测</h3>
    <p class="sub">只做本机检查，不会下载任何东西，也不会改动已有文件。</p>

    <div class="gatebox">
      <div class="gtop"><b>SDV 换声</b>${badge(sdv.ok)}</div>
      <div class="gsub">把已有的人声换成目标音色 · 约 ${sdv.sizeGB} GB · 需要 ${esc(sdv.vram || '')} 显存</div>
      <div class="gpath">${esc(sdv.root || '（未配置路径）')}</div>
      ${sdv.ok ? '' : `<div class="gpath">建议解压到：${esc(sdv.want || '')}\\</div>`}
      ${sdv.ok ? '' : `<div class="gmiss">${esc(miss(sdv))}</div>`}
      <div class="gbtns">
        ${sdv.ok ? '<button class="btn primary" data-enter>确定</button>'
                 : '<button class="btn primary" id="gSdv">下载并安装</button><button class="btn" data-enter>先跳过</button>'}
      </div>
    </div>

    <div class="gatebox">
      <div class="gtop"><b>TTS 造声</b>${badge(tts.ok)}</div>
      <div class="gsub">从文字直接生成语音 · 约 ${tts.sizeGB} GB · 需要 ${esc(tts.vram || '')} 显存</div>
      <div class="gpath">${esc(tts.root || '（未配置路径）')}</div>
      ${tts.ok ? '' : `<div class="gpath">建议解压到：${esc(tts.want || '')}\\</div>`}
      ${tts.ok ? '' : `<div class="gmiss">${esc(miss(tts))}</div>`}
      <div class="langs">
        <div><span class="lg ok">能造</span>${(tl.ok || []).map(esc).join('　')}</div>
        <div><span class="lg maybe">待验证</span>${(tl.maybe || []).map(esc).join('　')}</div>
        <div><span class="lg bad">不会说</span>${(tl.bad || []).map(esc).join('、')}</div>
        <p class="tiny muted">${esc(tl.note || '')}</p>
      </div>
      <div class="gbtns">
        ${tts.ok ? '<button class="btn primary" data-enter>确定</button>'
                 : '<button class="btn primary" id="gTts">下载并安装</button><button class="btn" data-enter>先跳过</button>'}
      </div>
      <button class="btn blue" id="gOther">我想做其他语言的造声 →</button>
    </div>

    <div class="gatebox">
      <div class="gtop"><b>FMOD Studio</b>${badge(fmodOk)}${fmodOk ? '<span class="gb ok">.fspro 工程已就位</span>' : ''}</div>
      <div class="gsub">把音频打成游戏认的 <code>.bank</code>。这一步<b>由工程自己调它的命令行完成</b>，你不用手动开 FMOD。</div>
      <div class="gpath">${esc(fmodCli || '（未找到 fmodstudiocl.exe）')}</div>
      ${fmodProj ? `<div class="gpath">工程：${esc(fmodProj)}</div>`
                 : `<div class="gpath">模组包目录：${esc(fmodKit || '（未配置）')}</div>`}
      ${fmodCli && !fmodProj ? '<div class="gmiss">找到了命令行，但没找到 .fspro 模组工程 —— 到右上角「设置」里把 FMOD 模组包目录指对</div>' : ''}
      ${!fmodCli ? '<div class="gmiss">没找到 FMOD Studio。SDV 和 TTS 能正常用，但做出来的语音没法打包成游戏要的 bank</div>' : ''}
      <div class="gbtns">
        ${fmodOk ? '<button class="btn primary" data-enter>确定</button>'
                 : '<button class="btn primary" id="gFmod">从哪拿</button><button class="btn" data-enter>先跳过</button>'}
      </div>
    </div>

    <div class="gatebox soft">
      <div class="gtop"><b>共享运行时</b>${sh.ok ? '<span class="gb ok">✓ 已共用</span>' : '<span class="gb warn">两套独立</span>'}</div>
      <div class="gsub">${esc(sh.note || '')}</div>
    </div>

    <div class="foot">
      <button class="btn primary" data-enter>确定</button>
    </div>`,
    box => {
      const go = () => closeModal();
      box.querySelectorAll('[data-enter]').forEach(b => b.onclick = go);
      box.querySelector('#gOther').onclick = openOtherTts;
      const s1 = box.querySelector('#gSdv'), s2 = box.querySelector('#gTts');
      if (s1) s1.onclick = () => openDownload('SDV 换声 · SeedVC', 'sdv');
      if (s2) s2.onclick = () => openDownload('TTS 造声 · IndexTTS2', 'tts');
      const s3 = box.querySelector('#gFmod');
      if (s3) s3.onclick = () => openDownload('FMOD Studio · 打包 bank 用', 'fmod');
    });
}

/* ------------------------------------------------ 头像 */

function renderAvatars() {
  const cats = (S.avatars || []);
  const total = cats.reduce((a, c) => a + (c.count || 0), 0);
  $('avatarHint').textContent = total ? `已提取 ${total} 个` : '还没提取过';
  $('avatarCount').textContent = total ? `已提取 ${total} 个 →` : '进入 →';
  $('avatarEmpty').hidden = total > 0;
  if (!cats.length) { $('avatarTabs').innerHTML = ''; $('avatarGrid').innerHTML = ''; return; }
  const cur = cats.find(c => c.key === avatarTab) || cats[0];
  avatarTab = cur.key;
  $('avatarTabs').innerHTML = cats.map(c =>
    `<button class="subtab${c.key === avatarTab ? ' active' : ''}" data-c="${c.key}">${esc(c.label)}<span class="muted"> ${c.count}</span></button>`).join('');
  $$('#avatarTabs .subtab').forEach(b => b.onclick = () => { avatarTab = b.dataset.c; renderAvatars(); });
  curAvatarFiles = cur.files || [];
  $('avatarGrid').innerHTML = curAvatarFiles.map((f, i) => {
    const tip = [f.file, f.en,
      (f.official && f.official !== f.zh ? '游戏内官方名：' + f.official : ''),
      (f.fixed ? '（本工程修正过译名）' : '')].filter(Boolean).join('\n');
    return `<div class="avcard" data-i="${i}" data-tip="${esc(tip)}">
      <div class="avthumb"><img loading="lazy" src="${f.url}" alt=""></div>
      <div class="avname">${esc(f.zh || f.id)}${f.fixed ? '<span class="fixmark" title="本工程修正过译名">改</span>' : ''}</div>
      <div class="avid muted">${esc(f.id.replace(/^cardicon_|^frame_|^profile_header_/, ''))}</div>
    </div>`;
  }).join('');
}
function f_html(x) { return x.file + (x.en ? '\n' + x.en : ''); }

function openAvatarBig(f) {
  openModal(`<button class="modal-x" data-close title="关闭">×</button>
    <h3>${esc(f.zh || f.id)}</h3>
    <p class="sub">文件名：<code>${esc(f.file)}</code>${f.en ? '　·　' + esc(f.en) : ''}</p>
    <div class="avbigwrap">
      <img id="avBigImg" src="${f.url}" alt="">
      <button class="btn primary dlbtn" id="avDl">下载 PNG</button>
    </div>
    ${f.intro
        ? `<div class="avintro">${esc(f.intro)}</div>`
        : (f.desc
            ? `<div class="avintro muted">游戏内说明：${esc(f.desc)}</div>`
            : (f.gen
                ? `<div class="avintro muted">${esc(f.gen)}</div>`
                : '<div class="avintro muted">这个头像在游戏里没有附带背景说明。</div>'))}
    ${f.official && f.official !== f.zh ? `<p class="tiny muted">游戏内官方中文名：${esc(f.official)}</p>` : ''}
    <div class="foot"><button class="btn" data-close>关闭</button></div>`,
    box => {
      box.querySelector('#avDl').onclick = () => downloadAvatar(box.querySelector('#avBigImg'), f.id);
    });
}

// 浏览器自己把 AVIF 画到 canvas 再导出 PNG，不依赖 ffmpeg
function downloadAvatar(img, name) {
  const go = () => {
    try {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      c.getContext('2d').drawImage(img, 0, 0);
      c.toBlob(b => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(b);
        a.download = name + '.png';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        toast('已下载 ' + name + '.png');
      }, 'image/png');
    } catch (e) { toast('转换失败：' + e.message, 'err'); }
  };
  if (img.complete && img.naturalWidth) go();
  else img.onload = go;
}

/* ------------------------------------------------ 启动 */

/* ------------------------------------------------ 首次启动：确认素材在哪（只带路，不替你解） */

function firstRunNeeded() {
  const V = (S || {}).voice || {};
  if (!V.gameRoot) return false;                                   // 没找到游戏，提不了
  const anyVoice = (V.sources || []).some(s => (s.extracted || 0) > 0);
  return !anyVoice;                                                // 一条原版语音都没提过 = 全新用户
}

function openFirstRun() {
  const V = (S || {}).voice || {};
  // 只取八大系的主录音，不要「备用录音」那几套
  const mains = (V.sources || []).filter(s => s.cat === 'ground' && s.main && s.available && !s.alt);
  const todo = mains.filter(s => !s.extracted);
  const avTotal = ((S || {}).avatars || []).reduce((a, c) => a + (c.count || 0), 0);
  const est = Math.round(todo.reduce((a, s) => a + (s.bankMB || 0), 0) * 1.2);
  const names = [...new Set(todo.map(s => s.label))];
  openModal(`<button class="modal-x" data-close title="关闭">×</button>
    <h3>第一次使用 · 先确认素材在哪儿</h3>
    <p class="sub">做语音包的原料，得从<b>你自己的游戏</b>里解出来。这一步只读本机文件，不联网、也不改动游戏本体。</p>

    <div class="gatebox">
      <div class="gtop"><b>已经找到你的游戏</b></div>
      <div class="gpath">游戏目录：${esc(V.gameRoot)}</div>
      <div class="gsub">里面一共收录了 ${(V.sources || []).length} 个语种的乘员语音。解哪个、解几个由你说了算，
        工具不会替你一次性全解一遍。</div>
    </div>

    <div class="gatebox soft">
      <div class="gtop"><b>接下来去哪</b></div>
      <div class="gsub">
        点下面的按钮进「下载乘员组语音」，挑一个语种点一下才会开始解包 —— 建议先从八大系入手，
        素材量大、换声时口音问题也最少。
        ${names.length ? `<br/>目前还没解过的有：${names.map(esc).join('、')}${est ? `，加起来约 ${est} MB（估算）` : ''}。` : '<br/>八大系看起来都已经解过了，可以直接开始做。'}
        ${avTotal === 0 ? '<br/>头像在另一个栏目里，想要的时候再单独提，约 10 MB。' : ''}
        <br/>解出来的东西放在工具目录下的 <code>语音\\原版\\</code>，只有你自己这台机器上有。
        这些素材的版权属于 Gaijin，请勿二次分发。
      </div>
    </div>

    <div class="foot">
      <button class="btn" data-close>以后再说</button>
      <button class="btn primary" id="firstRunGo">去挑语种</button>
    </div>`,
    box => {
      const b = box.querySelector('#firstRunGo');
      if (b) b.onclick = () => {
        // 这个按钮只负责把人带到「下载乘员组语音」，解哪些由用户自己点。
        // 早先它会把头像＋八大系一次性排进队列自动解包，等于替用户做了决定。
        closeModal();
        setView('voice');
        setVTab('get');
        setCat('ground');
      };
    });
}

(function boot() {
  bindTips();
  $$('.homecard').forEach(c => c.onclick = () => {
    const g = c.dataset.gate;
    // 语音包：先进界面，再弹环境检测 —— 用户点完确认时已经在页面里了
    if (g === 'voice') { setView('voice'); openVoiceGate(); return; }
    setView(c.dataset.go);
  });
  $('btnGuide').onclick = () => { setView('voice'); openVoiceTut(0); };
  $('btnNotice').onclick = openNotice;
  $('btnExtractAvatars').onclick = async () => {
    if (!(S.env || {}).gameRoot && !S.voice.gameRoot) return toast('先在「设置」里填好游戏根目录', 'warn');
    startJob(await post('/api/avatars/extract', {}), '提取战雷头像');
  };
  $('btnOpenAvatarDir').onclick = () => post('/api/open', { target: 'avatars' });
  // 用事件委托：不管卡片怎么渲染，单击一定有效
  $('avatarGrid').onclick = e => {
    const card = e.target.closest('.avcard');
    if (!card) return;
    const f = curAvatarFiles[+card.dataset.i];
    if (f) openAvatarBig(f);
  };
  $$('#v-voice > .tabs .tab').forEach(b => b.onclick = () => setVTab(b.dataset.tab));
  $$('#v-voice .subtab').forEach(b => b.onclick = () => setCat(b.dataset.cat));
  $$('#p-conv .sw').forEach(b => b.onclick = () => setConv(b.dataset.conv));
  $('onlyMain').onchange = e => { onlyMain = e.target.checked; renderSources(); };
  $('btnRefresh').onclick = refresh;
  $('btnSettings').onclick = openSettings;

  const bindRange = (id, valId, fmt) => {
    const el = $(id), out = $(valId);
    const upd = () => { out.textContent = fmt(el.value); };
    el.oninput = upd; upd();
  };
  bindRange('sdvSteps', 'sdvStepsVal', v => v);
  bindRange('sdvPitch', 'sdvPitchVal', v => (v > 0 ? '+' : '') + v + ' 半音');
  bindRange('ttsPitch', 'ttsPitchVal', v => (v > 0 ? '+' : '') + v + ' 半音');

  $$('#p-conv .ms').forEach(b => b.onclick = () => {
    ttsMode = b.dataset.mode;
    $$('#p-conv .ms').forEach(x => x.classList.toggle('active', x === b));
    $('ttsManual').hidden = ttsMode !== 'manual';
    $('ttsFile').hidden = ttsMode !== 'file';
  });
  $('ttsPickTxt').onclick = () => $('ttsTxt').click();
  $('ttsTxt').onchange = async e => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    const raw = await f.text();
    $('ttsFileName').textContent = f.name + '（' + (raw.length / 1024).toFixed(1) + ' KB）';
    ttsEntries = parseScript(raw);
    renderTtsPreview();
    if (!ttsEntries.length) toast('没解析出内容 —— 检查每句是否以 WT + 四位数字开头', 'warn');
  };
  renderTtsPreview();

  $('sdvGo').onclick = async () => {
    const p = {
      src: $('sdvSrc').value, ref: $('sdvRef').value, dst: $('sdvDst').value,
      steps: +$('sdvSteps').value, f0: $('sdvF0').checked, pitch: +$('sdvPitch').value
    };
    if (!p.src || !p.ref || !p.dst) return toast('三个路径都要填', 'warn');
    startJob(await post('/api/voice/sdv', p), 'SDV 批量换声');
  };
  $('fxGo').onclick = async () => {
    const p = { src: $('fxSrc').value, dst: $('fxDst').value, preset: $('fxPreset').value };
    if (!p.src || !p.dst) return toast('源和输出文件夹都要填', 'warn');
    startJob(await post('/api/voice/radio', p), '无线电效果');
  };

  $('ttsGo').onclick = async () => {
    const ref = $('ttsRef').value, dst = $('ttsDst').value;
    if (!ref || !dst) return toast('参考音色和输出文件夹都要填', 'warn');
    const base = { ref, dst, emoRef: $('ttsEmo').value, lang: $('ttsLang').value, pitch: +$('ttsPitch').value };
    let payload;
    if (ttsMode === 'file') {
      if (!ttsEntries.length) return toast('先选一个 TXT 稿子', 'warn');
      payload = Object.assign(base, { entries: ttsEntries });
    } else {
      const text = $('ttsText').value;
      if (!text.trim()) return toast('文本是空的', 'warn');
      payload = Object.assign(base, { text });
    }
    startJob(await post('/api/voice/tts', payload), 'TTS 批量生成');
  };

  $('scanGo').onclick = async () => {
    const src = $('fmodSrc').value;
    const out = $('scanOut');
    if (!src) return toast('先选一个素材文件夹', 'warn');
    out.innerHTML = '<p class="tiny muted">正在分析…</p>';
    const r = await post('/api/voice/scan-material', { src });
    if (!r.ok) { out.innerHTML = `<div class="gmiss">${esc(r.error || '分析失败')}</div>`; return; }
    renderScan(r.result);
  };
  $('btnOpenFmod').onclick = () => post('/api/open', { target: 'fmodkit' });
  $('btnPickPackZip').onclick = () => $('packZip').click();
  $('packZip').onchange = e => { if (e.target.files[0]) installFromZip(e.target.files[0]); e.target.value = ''; };
  $('btnOpenModDir').onclick = () => post('/api/open', { target: 'mod' });
  $('btnCleanMod').onclick = async () => {
    if (!confirm('清空 sound\\mod 里所有 .bank？')) return;
    const r = await post('/api/voice/uninstall-all', {});
    r.ok ? log('✓ ' + r.message) : log('✗ ' + r.error, 'err');
    await refresh();
  };

  document.addEventListener('click', e => {
    const b = e.target.closest('[data-browse]');
    if (b) openBrowser(b.dataset.browse, b.dataset.mode || 'dir');
  });

  $('logToggle').onclick = () => {
    $('console').classList.toggle('collapsed');
    $('logToggle').textContent = $('console').classList.contains('collapsed') ? '展开' : '收起';
  };
  $('logClear').onclick = () => { $('log').textContent = ''; };

  let depth = 0;
  window.addEventListener('dragenter', e => { e.preventDefault(); depth++; $('dropOverlay').classList.add('show'); });
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('dragleave', e => { e.preventDefault(); if (--depth <= 0) { depth = 0; $('dropOverlay').classList.remove('show'); } });
  window.addEventListener('drop', async e => {
    e.preventDefault(); depth = 0; $('dropOverlay').classList.remove('show');
    const files = []; const items = e.dataTransfer.items;
    if (items && items.length && items[0].webkitGetAsEntry) {
      for (const it of items) { const en = it.webkitGetAsEntry(); if (en) files.push(...await readEntry(en)); }
    } else files.push(...e.dataTransfer.files);
    if (view === 'voice' && files.length === 1 && /\.zip$/i.test(files[0].name)) await installFromZip(files[0]);
    else toast('拖进来的东西没认出来 —— 语音包 zip 请在「安装 / 打包」页拖入', 'warn');
  });
  async function readEntry(entry, path) {
    path = path || '';
    if (entry.isFile) return await new Promise(res => entry.file(f => { f.webkitRelativePath = path + entry.name; res([f]); }));
    if (entry.isDirectory) {
      const reader = entry.createReader(), all = [];
      while (true) {
        const ents = await new Promise(res => reader.readEntries(res));
        if (!ents.length) break;
        for (const e of ents) all.push(...await readEntry(e, path + entry.name + '/'));
      }
      return all;
    }
    return [];
  }

  $('modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  crumbs();
  refresh().then(() => { if (firstRunNeeded()) setTimeout(openFirstRun, 500); });
})();
