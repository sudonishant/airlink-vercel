/**
 * AirLink - Telegram Style PC <-> Mobile Sync
 * Client Application Logic
 */

(function () {
  'use strict';

  // State
  let items = [];
  let searchQuery = '';
  let ws = null;
  let reconnectInterval = 1000;
  let isSoundEnabled = true;
  let isAutoCopyEnabled = false;
  let currentRotation = 0;
  let mediaRecorder = null;
  let audioChunks = [];
  let recordingStartTime = 0;
  let recordingTimerInterval = null;
  let networkInfo = null;

  // New Feature States
  let currentUserName = localStorage.getItem('airlink_user_name') || '';
  let isViewOnceActive = false;
  let currentPinnedId = null;

  // Detect Device Platform
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  const defaultDevice = isMobile 
    ? (/iPhone|iPad|iPod/i.test(navigator.userAgent) ? 'iPhone' : 'Android') 
    : 'Kali PC';
  let deviceName = currentUserName || defaultDevice;

  // DOM Elements
  const feedContainer = document.getElementById('feed-container');
  const feedList = document.getElementById('feed-list');
  const emptyState = document.getElementById('empty-state');
  
  const textInput = document.getElementById('text-input');
  const btnSend = document.getElementById('btn-send');
  const btnRecordVoice = document.getElementById('btn-record-voice');
  const fileInput = document.getElementById('file-input');
  const cameraInput = document.getElementById('camera-input');
  
  const btnAttachFile = document.getElementById('btn-attach-file');
  const btnOpenCamera = document.getElementById('btn-open-camera');
  const btnViewOnce = document.getElementById('btn-view-once');
  const btnQuickPhoto = document.getElementById('btn-quick-photo');
  const btnQuickFile = document.getElementById('btn-quick-file');

  const tgBtnSearch = document.getElementById('tg-btn-search');
  const tgSearchBar = document.getElementById('tg-search-bar');
  const searchInput = document.getElementById('search-input');
  const clearSearchBtn = document.getElementById('clear-search');
  
  const tgStatusText = document.getElementById('tg-status-text');
  const currentDeviceTag = document.getElementById('current-device-tag');
  const btnToggleSound = document.getElementById('btn-toggle-sound');
  const soundIcon = document.getElementById('sound-icon');
  const btnToggleAutoCopy = document.getElementById('btn-toggle-autocopy');
  const autoCopyIcon = document.getElementById('autocopy-icon');
  
  const btnQrModal = document.getElementById('btn-qr-modal');
  const qrModal = document.getElementById('qr-modal');
  const btnCloseQrModal = document.getElementById('btn-close-qr-modal');
  const qrImage = document.getElementById('qr-image');
  const ipSelect = document.getElementById('ip-select');
  const directUrlInput = document.getElementById('direct-url-input');
  const btnCopyUrl = document.getElementById('btn-copy-url');

  const btnMoreMenu = document.getElementById('btn-more-menu');
  const moreMenuDropdown = document.getElementById('more-menu-dropdown');
  const btnClearHistory = document.getElementById('btn-clear-history');
  const btnOpenChangeName = document.getElementById('btn-open-change-name');

  const pinnedBar = document.getElementById('pinned-bar');
  const pinnedText = document.getElementById('pinned-text');
  const btnUnpin = document.getElementById('btn-unpin');

  const nameModal = document.getElementById('name-modal');
  const initialNameInput = document.getElementById('initial-name-input');
  const btnSaveInitialName = document.getElementById('btn-save-initial-name');

  const changeNameModal = document.getElementById('change-name-modal');
  const newNameInput = document.getElementById('new-name-input');
  const btnCancelChangeName = document.getElementById('btn-cancel-change-name');
  const btnConfirmChangeName = document.getElementById('btn-confirm-change-name');

  const uploadProgressContainer = document.getElementById('upload-progress-container');
  const uploadStatusText = document.getElementById('upload-status-text');
  const uploadPercentage = document.getElementById('upload-percentage');
  const uploadProgressFill = document.getElementById('upload-progress-fill');

  const voiceOverlay = document.getElementById('voice-recording-overlay');
  const recordingTimer = document.getElementById('recording-timer');
  const btnCancelRecording = document.getElementById('btn-cancel-recording');
  const btnSendRecording = document.getElementById('btn-send-recording');

  const dragOverlay = document.getElementById('drag-overlay');

  const lightboxModal = document.getElementById('lightbox-modal');
  const lightboxImage = document.getElementById('lightbox-image');
  const lightboxTitle = document.getElementById('lightbox-title');
  const lightboxDownload = document.getElementById('lightbox-download');
  const lightboxRotate = document.getElementById('lightbox-rotate');
  const lightboxClose = document.getElementById('lightbox-close');

  const toastContainer = document.getElementById('toast-container');

  // Initialize
  function init() {
    checkNameOnboarding();
    loadLocalSettings();
    initWebSocket();
    fetchHistory();
    fetchSystemInfo();
    setupEventListeners();
    registerServiceWorker();
  }

  // Name Onboarding Check
  function checkNameOnboarding() {
    currentUserName = localStorage.getItem('airlink_user_name') || '';
    if (!currentUserName) {
      nameModal.classList.remove('hidden');
      setTimeout(() => initialNameInput && initialNameInput.focus(), 250);
    } else {
      deviceName = currentUserName;
      currentDeviceTag.textContent = currentUserName;
    }
  }

  function loadLocalSettings() {
    const savedSound = localStorage.getItem('airlink_sound');
    if (savedSound !== null) isSoundEnabled = savedSound === 'true';
    soundIcon.textContent = isSoundEnabled ? '🔔' : '🔕';

    const savedAutoCopy = localStorage.getItem('airlink_autocopy');
    if (savedAutoCopy !== null) isAutoCopyEnabled = savedAutoCopy === 'true';
    autoCopyIcon.textContent = isAutoCopyEnabled ? '📋' : '📑';
  }

  // Audio Notification Synthesizer
  function playNotificationSound() {
    if (!isSoundEnabled) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(659.25, now);
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.1);

      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(0.25, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.3);
    } catch (e) {}
  }

  // Toast Notification
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `tg-toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(30px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 2800);
  }

  // WebSocket & Smart Polling Connection (for Vercel Cloud Serverless)
  let pollInterval = null;

  function initWebSocket() {
    const isVercel = window.location.hostname.includes('vercel.app');
    
    if (isVercel) {
      tgStatusText.textContent = 'online (cloud)';
      tgStatusText.style.color = 'var(--tg-accent-cyan)';
      startPolling();
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        tgStatusText.textContent = 'online';
        tgStatusText.style.color = 'var(--tg-accent-cyan)';
        reconnectInterval = 1000;
        if (pollInterval) clearInterval(pollInterval);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessage(data);
        } catch (err) {
          console.error('Error parsing WS message:', err);
        }
      };

      ws.onclose = () => {
        tgStatusText.textContent = 'connecting...';
        tgStatusText.style.color = 'var(--tg-text-secondary)';
        startPolling();
        setTimeout(initWebSocket, reconnectInterval);
        reconnectInterval = Math.min(reconnectInterval * 1.5, 10000);
      };

      ws.onerror = () => {
        startPolling();
        ws.close();
      };
    } catch (e) {
      startPolling();
    }
  }

  let unreadCount = 0;
  const originalDocumentTitle = document.title;

  window.addEventListener('focus', () => {
    unreadCount = 0;
    document.title = originalDocumentTitle;
  });

  function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(async () => {
      try {
        const res = await fetch('/history');
        if (res.ok) {
          const data = await res.json();
          const newItems = (data.items || []).reverse();
          const newPinnedId = data.pinned_id || null;

          if (newPinnedId !== currentPinnedId) {
            currentPinnedId = newPinnedId;
            updatePinnedBar();
          }

          // Check if items changed
          const prevIds = new Set(items.map(x => x.id));
          const hasChanges = JSON.stringify(newItems.map(x => x.id + (x.is_consumed ? 'c' : ''))) !== 
                             JSON.stringify(items.map(x => x.id + (x.is_consumed ? 'c' : '')));

          if (hasChanges) {
            const freshArrivals = newItems.filter(x => !prevIds.has(x.id));
            items = newItems;
            renderFeed();
            updatePinnedBar();
            scrollToBottom(); // Auto-scroll to show new message immediately!

            // Alert user for newly arrived items from other devices
            freshArrivals.forEach(newItem => {
              if (newItem.sender !== deviceName && newItem.type !== 'system') {
                playNotificationSound();
                showToast(`New ${newItem.category} from ${newItem.sender} 🚀`, 'success');

                if (!document.hasFocus()) {
                  unreadCount++;
                  document.title = `(${unreadCount}) 💬 New Message - AirLink`;
                }

                if (newItem.type === 'text' && isAutoCopyEnabled && !newItem.is_view_once) {
                  navigator.clipboard.writeText(newItem.content).catch(() => {});
                }
              }
            });
          }
        }
      } catch (e) {}
    }, 1000); // ⚡ Fast 1-second auto-refresh!
  }

  function handleWebSocketMessage(data) {
    if (data.type === 'new_item') {
      const item = data.item;
      if (!items.some(x => x.id === item.id)) {
        items.push(item);
        renderFeed();
        scrollToBottom();
        playNotificationSound();
      }

      if (item.sender !== deviceName) {
        showToast(`New ${item.category} from ${item.sender}`, 'success');

        if (item.type === 'text' && isAutoCopyEnabled && !item.is_view_once) {
          navigator.clipboard.writeText(item.content).catch(() => {});
        }
      }
    } else if (data.type === 'item_deleted') {
      items = items.filter(x => x.id !== data.id);
      if (currentPinnedId === data.id) {
        currentPinnedId = null;
        updatePinnedBar();
      }
      renderFeed();
    } else if (data.type === 'history_cleared') {
      items = [];
      currentPinnedId = null;
      updatePinnedBar();
      renderFeed();
    }
  }

  // Fetch History from Server
  async function fetchHistory() {
    try {
      const res = await fetch('/history');
      if (res.ok) {
        const data = await res.json();
        items = (data.items || []).reverse();
        currentPinnedId = data.pinned_id || null;
        renderFeed();
        updatePinnedBar();
        scrollToBottom();
      }
    } catch (err) {
      console.warn('Could not fetch history:', err);
    }
  }

  async function fetchSystemInfo() {
    try {
      const res = await fetch('/info');
      if (res.ok) {
        networkInfo = await res.json();
        if (networkInfo.pinned_id) {
          currentPinnedId = networkInfo.pinned_id;
          updatePinnedBar();
        }
        populateNetworkIPs();
      }
    } catch (err) {
      console.warn('Could not fetch system info:', err);
    }
  }

  function populateNetworkIPs() {
    if (!networkInfo || !ipSelect) return;
    ipSelect.innerHTML = '';

    const port = networkInfo.port || 5000;

    if (networkInfo.global_url) {
      const globOpt = document.createElement('option');
      globOpt.value = networkInfo.global_url;
      globOpt.textContent = `🌐 Anywhere / Internet: ${networkInfo.global_url}`;
      ipSelect.appendChild(globOpt);
    }

    if (networkInfo.hostname) {
      const hostOpt = document.createElement('option');
      hostOpt.value = `http://${networkInfo.hostname}.local:${port}`;
      hostOpt.textContent = `⭐ Local Wi-Fi: ${networkInfo.hostname}.local`;
      ipSelect.appendChild(hostOpt);
    }
    
    if (networkInfo.ips) {
      networkInfo.ips.forEach(iface => {
        const opt = document.createElement('option');
        opt.value = `http://${iface.ip}:${port}`;
        opt.textContent = `👉 Wi-Fi IP: ${iface.ip} (${iface.interface})`;
        ipSelect.appendChild(opt);
      });
    }

    updateSelectedIP();
  }

  function updateSelectedIP() {
    if (!ipSelect || !directUrlInput || !qrImage) return;
    const selectedUrl = ipSelect.value || window.location.origin;
    directUrlInput.value = selectedUrl;
    
    const isGlobal = selectedUrl.startsWith('https://') && !selectedUrl.includes('.local');
    if (isGlobal) {
      qrImage.src = `/api/qr?global_link=true&t=${Date.now()}`;
    } else {
      qrImage.src = `/api/qr?ip=${encodeURIComponent(ipSelect.value || window.location.hostname)}&port=${networkInfo ? networkInfo.port : 5000}&t=${Date.now()}`;
    }
  }

  function scrollToBottom() {
    setTimeout(() => {
      feedContainer.scrollTop = feedContainer.scrollHeight;
    }, 50);
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';
    try {
      const date = new Date(timestamp.replace(' ', 'T'));
      if (!isNaN(date.getTime())) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
    } catch (e) {}
    const parts = timestamp.split(' ');
    if (parts.length > 1) return parts[1].substring(0, 5);
    return timestamp;
  }

  // Render Telegram Feed
  function renderFeed() {
    const filtered = items.filter(item => {
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const textMatch = item.content && item.content.toLowerCase().includes(q);
        const filenameMatch = item.filename && item.filename.toLowerCase().includes(q);
        const senderMatch = item.sender && item.sender.toLowerCase().includes(q);
        return textMatch || filenameMatch || senderMatch;
      }
      return true;
    });

    if (filtered.length === 0) {
      feedList.innerHTML = '';
      emptyState.classList.remove('hidden');
      return;
    }

    emptyState.classList.add('hidden');
    feedList.innerHTML = '';

    filtered.forEach(item => {
      const bubble = createTelegramBubble(item);
      feedList.appendChild(bubble);
    });
  }

  // Create Telegram Chat Bubble
  function createTelegramBubble(item) {
    // 📢 System Message (Name change alert)
    if (item.type === 'system' || item.category === 'system') {
      const row = document.createElement('div');
      row.className = 'tg-msg-row system';
      row.dataset.id = item.id;
      row.innerHTML = `<div class="tg-system-pill">${escapeHtml(item.content)}</div>`;
      return row;
    }

    const isOutgoing = (item.sender === deviceName);
    
    const row = document.createElement('div');
    row.className = `tg-msg-row ${isOutgoing ? 'outgoing' : 'incoming'}`;
    row.dataset.id = item.id;

    const bubble = document.createElement('div');
    bubble.className = 'tg-bubble';

    // Top action controls (Pin & Delete)
    const btnBox = document.createElement('div');
    btnBox.className = 'tg-bubble-actions';
    btnBox.style.cssText = 'position: absolute; top: 4px; right: 6px; display: flex; gap: 4px; opacity: 0; transition: opacity 0.15s; z-index: 5;';

    // Pin Button
    const btnPin = document.createElement('button');
    btnPin.className = 'tg-bubble-action-btn';
    btnPin.title = 'Pin message';
    btnPin.innerHTML = '📌';
    btnPin.style.cssText = 'background: rgba(0,0,0,0.4); border: none; color: #fff; border-radius: 50%; width: 22px; height: 22px; font-size: 0.7rem; cursor: pointer; display: flex; align-items: center; justify-content: center;';
    btnPin.onclick = (e) => {
      e.stopPropagation();
      pinMessage(item.id);
    };
    btnBox.appendChild(btnPin);

    // Delete Button - ONLY for outgoing messages (User can ONLY delete their own messages!)
    if (isOutgoing) {
      const btnDel = document.createElement('button');
      btnDel.className = 'tg-bubble-action-btn';
      btnDel.title = 'Delete my message';
      btnDel.innerHTML = '✕';
      btnDel.style.cssText = 'background: rgba(0,0,0,0.4); border: none; color: #fff; border-radius: 50%; width: 22px; height: 22px; font-size: 0.7rem; cursor: pointer; display: flex; align-items: center; justify-content: center;';
      btnDel.onclick = (e) => {
        e.stopPropagation();
        deleteItem(item.id);
      };
      btnBox.appendChild(btnDel);
    }

    bubble.onmouseenter = () => { btnBox.style.opacity = '1'; };
    bubble.onmouseleave = () => { btnBox.style.opacity = '0'; };
    bubble.appendChild(btnBox);

    // Incoming Sender Label
    if (!isOutgoing) {
      const sender = document.createElement('div');
      sender.className = 'tg-bubble-sender';
      sender.textContent = item.sender || 'Friend';
      bubble.appendChild(sender);
    }

    // 🔂 View Once Card Rendering
    if (item.is_view_once) {
      const voCard = document.createElement('div');
      voCard.className = `tg-view-once-card ${item.is_consumed ? 'consumed' : ''}`;

      if (item.is_consumed) {
        voCard.innerHTML = `
          <div class="tg-vo-icon">1️⃣</div>
          <div class="tg-vo-info">
            <div class="tg-vo-title">View Once ${item.category === 'image' ? 'Photo' : 'Message'}</div>
            <div class="tg-vo-desc">Opened / Expired</div>
          </div>
        `;
      } else {
        voCard.innerHTML = `
          <div class="tg-vo-icon">1️⃣</div>
          <div class="tg-vo-info">
            <div class="tg-vo-title">View Once ${item.category === 'image' ? 'Photo' : 'Message'}</div>
            <div class="tg-vo-desc">${isOutgoing ? 'Sent (One-time view)' : 'Tap to view (Disappears after opening)'}</div>
          </div>
        `;
        voCard.onclick = () => {
          handleViewOnceClick(item);
        };
      }
      bubble.appendChild(voCard);
    } else {
      // Standard Permanent Content Rendering
      if (item.type === 'text') {
        if (item.is_url) {
          const urlEl = document.createElement('a');
          urlEl.className = 'tg-bubble-url';
          urlEl.href = item.content;
          urlEl.target = '_blank';
          urlEl.rel = 'noopener';
          urlEl.textContent = item.content;
          bubble.appendChild(urlEl);
        } else {
          const textEl = document.createElement('div');
          textEl.className = 'tg-bubble-text';
          textEl.textContent = item.content;
          bubble.appendChild(textEl);
        }
      } else if (item.category === 'image') {
        const mediaWrap = document.createElement('div');
        mediaWrap.className = 'tg-media-image';
        mediaWrap.onclick = () => openLightbox(item.view_url, item.filename, item.download_url);

        const img = document.createElement('img');
        img.src = item.view_url;
        img.alt = item.filename;
        img.loading = 'lazy';
        mediaWrap.appendChild(img);
        bubble.appendChild(mediaWrap);
      } else if (item.category === 'audio') {
        const audioWrap = document.createElement('div');
        audioWrap.className = 'tg-audio-bubble';
        audioWrap.innerHTML = `
          <div style="font-size: 0.8rem; color: var(--tg-text-secondary); margin-bottom: 2px;">🎙️ ${escapeHtml(item.filename)} (${item.formatted_size})</div>
          <audio controls preload="metadata" src="${item.view_url}"></audio>
        `;
        bubble.appendChild(audioWrap);
      } else if (item.category === 'video') {
        const videoWrap = document.createElement('div');
        videoWrap.className = 'tg-video-bubble';
        videoWrap.innerHTML = `
          <video controls preload="metadata" src="${item.view_url}"></video>
          <div style="font-size: 0.75rem; color: var(--tg-text-secondary); margin-top: 4px;">${escapeHtml(item.filename)} (${item.formatted_size})</div>
        `;
        bubble.appendChild(videoWrap);
      } else {
        // Document / Archive File
        const ext = (item.filename && item.filename.includes('.')) 
          ? item.filename.split('.').pop().substring(0, 4).toUpperCase() 
          : 'DOC';

        const fileCard = document.createElement('a');
        fileCard.className = 'tg-file-card';
        fileCard.href = item.download_url;
        fileCard.download = item.filename || 'file';
        fileCard.target = '_blank';
        fileCard.innerHTML = `
          <div class="tg-file-icon-wrap">
            <span class="tg-file-ext">${escapeHtml(ext)}</span>
          </div>
          <div class="tg-file-details">
            <div class="tg-file-name">${escapeHtml(item.original_name || item.filename)}</div>
            <div class="tg-file-meta">${item.formatted_size} • Click to Download</div>
          </div>
          <div class="tg-file-arrow">⬇️</div>
        `;
        bubble.appendChild(fileCard);
      }
    }

    // Bubble Metadata (Time, checks, pin status)
    const meta = document.createElement('div');
    meta.className = 'tg-bubble-meta';

    if (currentPinnedId === item.id) {
      const pinIndicator = document.createElement('span');
      pinIndicator.textContent = '📌 ';
      pinIndicator.title = 'Pinned Message';
      meta.appendChild(pinIndicator);
    }

    const timeSpan = document.createElement('span');
    timeSpan.className = 'tg-bubble-time';
    timeSpan.textContent = formatTime(item.timestamp);
    meta.appendChild(timeSpan);

    if (isOutgoing) {
      const checks = document.createElement('span');
      checks.className = 'tg-bubble-checks';
      checks.textContent = '✓✓';
      meta.appendChild(checks);
    }

    bubble.appendChild(meta);
    row.appendChild(bubble);
    return row;
  }

  // Handle View Once Item Click (STRICT 1-TIME VIEW ONLY)
  function handleViewOnceClick(item) {
    const isAlreadyOpened = item.is_consumed || localStorage.getItem('vo_opened_' + item.id) === 'true';
    if (isAlreadyOpened) {
      showToast('This message has already been opened! 🔂', 'info');
      return;
    }

    // Immediately mark consumed in localStorage and in-memory
    item.is_consumed = true;
    localStorage.setItem('vo_opened_' + item.id, 'true');

    if (item.category === 'image' && item.view_url) {
      const photoUrl = item.view_url;
      item.view_url = ''; // Erase immediately so it can never be retrieved
      lightboxDownload.style.display = 'none';
      openLightbox(photoUrl, '🔂 View Once Photo (Disappears on close)');
    } else {
      const textVal = item.content;
      item.content = '🔂 View Once Message (Opened)';
      alert(`🔂 View Once Message:\n\n${textVal}`);
      renderFeed();
    }

    // Inform server to burn this message permanently
    consumeViewOnce(item.id);
  }

  async function consumeViewOnce(itemId) {
    try {
      await fetch('/view_once/consume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: itemId })
      });
      const local = items.find(x => x.id === itemId);
      if (local) {
        local.is_consumed = true;
        local.view_url = '';
        local.content = '🔂 View Once (Opened)';
        renderFeed();
      }
    } catch (e) {}
  }

  // 📌 Pin & Unpin Handlers
  async function pinMessage(id) {
    try {
      const res = await fetch('/pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: id })
      });
      if (res.ok) {
        currentPinnedId = id;
        updatePinnedBar();
        renderFeed();
        showToast('Message pinned 📌', 'success');
      }
    } catch (e) {
      showToast('Could not pin message', 'error');
    }
  }

  async function unpinMessage() {
    try {
      const res = await fetch('/unpin', { method: 'POST' });
      if (res.ok) {
        currentPinnedId = null;
        updatePinnedBar();
        renderFeed();
        showToast('Message unpinned', 'info');
      }
    } catch (e) {
      showToast('Could not unpin message', 'error');
    }
  }

  function updatePinnedBar() {
    if (!pinnedBar || !pinnedText) return;
    if (!currentPinnedId) {
      pinnedBar.classList.add('hidden');
      return;
    }

    const pinnedItem = items.find(x => x.id === currentPinnedId);
    if (!pinnedItem) {
      pinnedBar.classList.add('hidden');
      return;
    }

    pinnedBar.classList.remove('hidden');
    let summary = '';
    if (pinnedItem.type === 'text') {
      summary = pinnedItem.content;
    } else if (pinnedItem.category === 'image') {
      summary = `📷 Photo (${pinnedItem.filename})`;
    } else {
      summary = `📎 ${pinnedItem.original_name || pinnedItem.filename}`;
    }
    pinnedText.textContent = `${pinnedItem.sender}: ${summary}`;
  }

  function jumpToPinnedMessage() {
    if (!currentPinnedId) return;
    const el = document.querySelector(`.tg-msg-row[data-id="${currentPinnedId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('highlight-pinned');
      setTimeout(() => el.classList.remove('highlight-pinned'), 2000);
    }
  }

  // Send Text Message (⚡ Ultra-Fast 0ms Optimistic Response)
  async function sendTextMessage() {
    const text = textInput.value.trim();
    if (!text) return;

    const isVO = isViewOnceActive;
    if (isViewOnceActive) {
      isViewOnceActive = false;
      btnViewOnce.classList.remove('active');
    }

    // 1. Instantly append to chat in 0ms (Zero delay!)
    const tempId = `temp_${Date.now()}`;
    const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 19);
    const tempItem = {
      id: tempId,
      type: 'text',
      category: 'text',
      content: text,
      is_url: text.startsWith('http://') || text.startsWith('https://'),
      sender: deviceName,
      is_view_once: isVO,
      is_consumed: false,
      timestamp: timestamp,
      time_epoch: Date.now() / 1000
    };

    items.push(tempItem);
    renderFeed();
    scrollToBottom();

    // 2. Clear input immediately so user can type next message
    textInput.value = '';
    textInput.style.height = 'auto';
    textInput.focus();

    // 3. Send in background
    try {
      const res = await fetch('/send/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          device: deviceName,
          is_view_once: isVO
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data && data.item) {
          const idx = items.findIndex(x => x.id === tempId);
          if (idx !== -1) {
            items[idx] = data.item;
          }
        }
      }
    } catch (err) {
      showToast('Error sending message', 'error');
    }
  }

  // Upload Files with Progress
  function uploadFiles(fileList, customCategory = null) {
    if (!fileList || fileList.length === 0) return;

    const isVO = isViewOnceActive;
    if (isViewOnceActive) {
      isViewOnceActive = false;
      btnViewOnce.classList.remove('active');
    }

    Array.from(fileList).forEach(file => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('sender', deviceName);
      formData.append('is_view_once', isVO ? 'true' : 'false');
      if (customCategory) formData.append('custom_type', customCategory);

      const xhr = new XMLHttpRequest();

      uploadProgressContainer.classList.remove('hidden');
      uploadStatusText.textContent = `Sending ${file.name}...`;

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const percent = Math.round((e.loaded / e.total) * 100);
          uploadPercentage.textContent = `${percent}%`;
          uploadProgressFill.style.width = `${percent}%`;
        }
      };

      xhr.onload = () => {
        uploadProgressContainer.classList.add('hidden');
        uploadProgressFill.style.width = '0%';
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const data = JSON.parse(xhr.responseText);
            if (data && data.item && !items.some(x => x.id === data.item.id)) {
              items.push(data.item);
              renderFeed();
              scrollToBottom();
            }
          } catch (e) {}
          showToast(`${file.name} sent 🚀`, 'success');
        } else {
          showToast(`Failed to send ${file.name}`, 'error');
        }
      };

      xhr.onerror = () => {
        uploadProgressContainer.classList.add('hidden');
        showToast(`Network error uploading ${file.name}`, 'error');
      };

      xhr.open('POST', '/send/file', true);
      xhr.send(formData);
    });
  }

  // Voice Note Recording
  async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast('Microphone not supported on this browser', 'error');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunks = [];
      mediaRecorder = new MediaRecorder(stream);

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop());
        clearInterval(recordingTimerInterval);
      };

      mediaRecorder.start();
      recordingStartTime = Date.now();
      voiceOverlay.classList.remove('hidden');

      recordingTimerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
        const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const secs = String(elapsed % 60).padStart(2, '0');
        recordingTimer.textContent = `${mins}:${secs}`;
      }, 500);
    } catch (err) {
      showToast('Microphone permission denied', 'error');
    }
  }

  function stopRecording(send = true) {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;

    mediaRecorder.onstop = () => {
      voiceOverlay.classList.add('hidden');
      clearInterval(recordingTimerInterval);

      if (send && audioChunks.length > 0) {
        const mimeType = mediaRecorder.mimeType || 'audio/webm';
        const blob = new Blob(audioChunks, { type: mimeType });
        const ext = mimeType.includes('ogg') ? 'ogg' : (mimeType.includes('mp4') ? 'm4a' : 'webm');
        const file = new File([blob], `VoiceNote_${Date.now()}.${ext}`, { type: mimeType });
        uploadFiles([file], 'audio');
      }
      audioChunks = [];
    };

    mediaRecorder.stop();
  }

  // Lightbox Viewer
  function openLightbox(url, title = 'Photo', downloadUrl = null) {
    lightboxImage.src = url;
    lightboxTitle.textContent = title;
    lightboxDownload.href = downloadUrl || url;
    lightboxDownload.download = title;
    currentRotation = 0;
    lightboxImage.style.transform = `rotate(0deg)`;
    lightboxModal.classList.remove('hidden');
  }

  function closeLightbox() {
    lightboxModal.classList.add('hidden');
    lightboxImage.src = '';
    lightboxDownload.style.display = ''; // restore download button for standard photos
    renderFeed(); // Re-render to ensure view once shows consumed
  }

  // Delete Item (ONLY own messages, with instant optimistic removal)
  async function deleteItem(id) {
    const item = items.find(x => x.id === id);
    if (item && item.sender !== deviceName) {
      showToast('You can only delete your own messages! ⚠️', 'error');
      return;
    }

    // Instantly remove from screen in 0ms!
    items = items.filter(x => x.id !== id);
    if (currentPinnedId === id) {
      currentPinnedId = null;
      updatePinnedBar();
    }
    renderFeed();
    showToast('Message deleted', 'info');

    try {
      await fetch(`/history/${id}?sender=${encodeURIComponent(deviceName)}`, { method: 'DELETE' });
    } catch (err) {}
  }

  async function clearAllHistory() {
    if (!confirm('Are you sure you want to clear all history?')) return;
    try {
      const res = await fetch('/history', { method: 'DELETE' });
      if (res.ok) {
        items = [];
        currentPinnedId = null;
        updatePinnedBar();
        renderFeed();
        showToast('History cleared', 'info');
      }
    } catch (err) {
      showToast('Failed to clear history', 'error');
    }
  }

  // Setup Event Listeners
  function setupEventListeners() {
    // 1️⃣ First-time Name Setup Save
    if (btnSaveInitialName) {
      btnSaveInitialName.addEventListener('click', () => {
        const name = initialNameInput.value.trim();
        if (!name) {
          showToast('Please enter your name', 'error');
          initialNameInput.focus();
          return;
        }
        localStorage.setItem('airlink_user_name', name);
        currentUserName = name;
        deviceName = name;
        currentDeviceTag.textContent = name;
        nameModal.classList.add('hidden');
        showToast(`Welcome, ${name}! ✈️`, 'success');
      });
      initialNameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') btnSaveInitialName.click();
      });
    }

    // ✏️ Change Name Flow with Announcement
    if (btnOpenChangeName) {
      btnOpenChangeName.addEventListener('click', () => {
        moreMenuDropdown.classList.remove('show');
        newNameInput.value = currentUserName || '';
        changeNameModal.classList.remove('hidden');
        setTimeout(() => newNameInput.focus(), 200);
      });
    }

    if (btnCancelChangeName) {
      btnCancelChangeName.addEventListener('click', () => {
        changeNameModal.classList.add('hidden');
      });
    }

    if (btnConfirmChangeName) {
      btnConfirmChangeName.addEventListener('click', async () => {
        const newName = newNameInput.value.trim();
        if (!newName) {
          showToast('Name cannot be empty', 'error');
          return;
        }
        if (newName === currentUserName) {
          changeNameModal.classList.add('hidden');
          return;
        }

        const oldName = currentUserName || 'Someone';
        localStorage.setItem('airlink_user_name', newName);
        currentUserName = newName;
        deviceName = newName;
        currentDeviceTag.textContent = newName;
        changeNameModal.classList.add('hidden');

        // Broadcast name change alert to everyone in chat!
        try {
          await fetch('/send/text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              text: `📢 "${oldName}" changed their name to "${newName}"`,
              device: newName,
              type: 'system'
            })
          });
          fetchHistory();
        } catch (e) {}

        showToast(`Name updated to ${newName} 📢`, 'success');
      });
      newNameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') btnConfirmChangeName.click();
      });
    }

    // 📌 Pinned Bar click to scroll
    if (pinnedBar) {
      pinnedBar.addEventListener('click', jumpToPinnedMessage);
    }
    if (btnUnpin) {
      btnUnpin.addEventListener('click', (e) => {
        e.stopPropagation();
        unpinMessage();
      });
    }

    // 🔂 View Once Toggle
    if (btnViewOnce) {
      btnViewOnce.addEventListener('click', () => {
        isViewOnceActive = !isViewOnceActive;
        btnViewOnce.classList.toggle('active', isViewOnceActive);
        showToast(`View Once ${isViewOnceActive ? 'Enabled 1️⃣ (Disappears after viewing)' : 'Disabled'}`, 'info');
      });
    }

    // Send Text on Click & Enter
    btnSend.addEventListener('click', sendTextMessage);
    textInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendTextMessage();
      }
    });

    // Auto-grow Textarea
    textInput.addEventListener('input', () => {
      textInput.style.height = 'auto';
      textInput.style.height = Math.min(textInput.scrollHeight, 120) + 'px';
    });

    // Attach File / Camera Triggers
    btnAttachFile.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length > 0) {
        uploadFiles(fileInput.files);
        fileInput.value = '';
      }
    });

    btnOpenCamera.addEventListener('click', () => cameraInput.click());
    cameraInput.addEventListener('change', () => {
      if (cameraInput.files.length > 0) {
        uploadFiles(cameraInput.files, 'image');
        cameraInput.value = '';
      }
    });

    if (btnQuickPhoto) {
      btnQuickPhoto.addEventListener('click', () => cameraInput.click());
    }
    if (btnQuickFile) {
      btnQuickFile.addEventListener('click', () => fileInput.click());
    }

    // Voice Record Buttons
    btnRecordVoice.addEventListener('click', () => {
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        stopRecording(true);
      } else {
        startRecording();
      }
    });
    btnCancelRecording.addEventListener('click', () => stopRecording(false));
    btnSendRecording.addEventListener('click', () => stopRecording(true));

    // Search Toggle
    tgBtnSearch.addEventListener('click', () => {
      tgSearchBar.classList.toggle('hidden');
      if (!tgSearchBar.classList.contains('hidden')) {
        searchInput.focus();
      } else {
        searchQuery = '';
        searchInput.value = '';
        renderFeed();
      }
    });

    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value;
      clearSearchBtn.classList.toggle('hidden', !searchQuery);
      renderFeed();
    });

    clearSearchBtn.addEventListener('click', () => {
      searchQuery = '';
      searchInput.value = '';
      clearSearchBtn.classList.add('hidden');
      renderFeed();
    });

    // Settings Toggles
    btnToggleSound.addEventListener('click', () => {
      isSoundEnabled = !isSoundEnabled;
      localStorage.setItem('airlink_sound', isSoundEnabled);
      soundIcon.textContent = isSoundEnabled ? '🔔' : '🔕';
      showToast(`Sound: ${isSoundEnabled ? 'Enabled' : 'Muted'}`, 'info');
    });

    btnToggleAutoCopy.addEventListener('click', () => {
      isAutoCopyEnabled = !isAutoCopyEnabled;
      localStorage.setItem('airlink_autocopy', isAutoCopyEnabled);
      autoCopyIcon.textContent = isAutoCopyEnabled ? '📋' : '📑';
      showToast(`Auto-copy: ${isAutoCopyEnabled ? 'ON' : 'OFF'}`, 'info');
      moreMenuDropdown.classList.remove('show');
    });

    // More Menu
    btnMoreMenu.addEventListener('click', (e) => {
      e.stopPropagation();
      moreMenuDropdown.classList.toggle('show');
    });

    document.addEventListener('click', () => {
      moreMenuDropdown.classList.remove('show');
    });

    btnClearHistory.addEventListener('click', clearAllHistory);

    // QR Modal
    if (btnQrModal) {
      btnQrModal.addEventListener('click', () => qrModal.classList.remove('hidden'));
    }
    if (btnCloseQrModal) {
      btnCloseQrModal.addEventListener('click', () => qrModal.classList.add('hidden'));
    }
    if (ipSelect) {
      ipSelect.addEventListener('change', updateSelectedIP);
    }
    if (btnCopyUrl) {
      btnCopyUrl.addEventListener('click', () => {
        navigator.clipboard.writeText(directUrlInput.value).then(() => {
          showToast('URL copied to clipboard!', 'success');
        });
      });
    }

    // Lightbox controls
    lightboxClose.addEventListener('click', closeLightbox);
    lightboxRotate.addEventListener('click', () => {
      currentRotation = (currentRotation + 90) % 360;
      lightboxImage.style.transform = `rotate(${currentRotation}deg)`;
    });

    // Drag and drop support
    window.addEventListener('dragenter', (e) => {
      e.preventDefault();
      dragOverlay.classList.remove('hidden');
    });

    dragOverlay.addEventListener('dragover', (e) => e.preventDefault());
    dragOverlay.addEventListener('dragleave', (e) => {
      if (e.relatedTarget === null || e.target === dragOverlay) {
        dragOverlay.classList.add('hidden');
      }
    });

    dragOverlay.addEventListener('drop', (e) => {
      e.preventDefault();
      dragOverlay.classList.add('hidden');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    });
  }

  // Register PWA Service Worker
  function registerServiceWorker() {
    if ('serviceWorker' in navigator && window.location.protocol === 'https:') {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
  }

  // Helper Escape HTML
  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Launch App
  window.addEventListener('DOMContentLoaded', init);
})();
