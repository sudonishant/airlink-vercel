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

  // Detect Device Name
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  const deviceName = isMobile 
    ? (/iPhone|iPad|iPod/i.test(navigator.userAgent) ? 'iPhone' : 'Android') 
    : 'Kali PC';

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
    currentDeviceTag.textContent = deviceName;
    loadLocalSettings();
    initWebSocket();
    fetchHistory();
    fetchSystemInfo();
    setupEventListeners();
    registerServiceWorker();
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

  // WebSocket & Smart Polling Connection (for Vercel Serverless)
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

  function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(async () => {
      try {
        const res = await fetch('/api/history');
        if (res.ok) {
          const data = await res.json();
          const newItems = (data.items || []).reverse();
          if (newItems.length !== items.length) {
            items = newItems;
            renderFeed();
            scrollToBottom();
          }
        }
      } catch (e) {}
    }, 3000);
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

        if (item.type === 'text' && isAutoCopyEnabled) {
          copyToClipboard(item.content, false);
          showToast('Text auto-copied to clipboard', 'info');
        }
      }
    } else if (data.type === 'item_deleted') {
      items = items.filter(x => x.id !== data.id);
      renderFeed();
    } else if (data.type === 'history_cleared') {
      items = [];
      renderFeed();
      showToast('All messages cleared', 'info');
    } else if (data.type === 'client_count') {
      const count = data.count || 1;
      tgStatusText.textContent = count > 1 ? `${count} devices online` : 'online';
    }
  }

  // Fetch History from Server
  async function fetchHistory() {
    try {
      const res = await fetch('/api/history');
      const data = await res.json();
      items = (data.items || []).reverse(); // Oldest first
      renderFeed();
      scrollToBottom();
    } catch (err) {
      console.error('Failed to fetch history:', err);
    }
  }

  // Fetch Network & System Info
  async function fetchSystemInfo() {
    try {
      const res = await fetch('/api/info');
      networkInfo = await res.json();
      populateNetworkIPs();
    } catch (err) {}
  }

  function populateNetworkIPs() {
    if (!networkInfo) return;
    ipSelect.innerHTML = '';

    const port = networkInfo.port || 5000;

    // 1. Add Global Internet URL first if available
    if (networkInfo.global_url) {
      const globOpt = document.createElement('option');
      globOpt.value = networkInfo.global_url;
      globOpt.textContent = `🌐 Anywhere / Internet: ${networkInfo.global_url}`;
      ipSelect.appendChild(globOpt);
    }

    // 2. Add .local permanent hostname option
    if (networkInfo.hostname) {
      const hostOpt = document.createElement('option');
      hostOpt.value = `http://${networkInfo.hostname}.local:${port}`;
      hostOpt.textContent = `⭐ Local Wi-Fi: ${networkInfo.hostname}.local`;
      ipSelect.appendChild(hostOpt);
    }
    
    // 3. Add Raw IP interfaces
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
    const isOutgoing = (item.sender === deviceName);
    
    const row = document.createElement('div');
    row.className = `tg-msg-row ${isOutgoing ? 'outgoing' : 'incoming'}`;
    row.dataset.id = item.id;

    const bubble = document.createElement('div');
    bubble.className = 'tg-bubble';

    // Delete Button on Hover
    const btnDel = document.createElement('button');
    btnDel.className = 'tg-bubble-delete';
    btnDel.title = 'Delete';
    btnDel.innerHTML = '✕';
    btnDel.onclick = (e) => {
      e.stopPropagation();
      deleteItem(item.id);
    };
    bubble.appendChild(btnDel);

    // Incoming Sender Label
    if (!isOutgoing) {
      const sender = document.createElement('div');
      sender.className = 'tg-bubble-sender';
      sender.textContent = item.sender || 'Other Device';
      bubble.appendChild(sender);
    }

    // Content based on category
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
      fileCard.innerHTML = `
        <div class="tg-file-icon-circle">${escapeHtml(ext)}</div>
        <div class="tg-file-info">
          <div class="tg-file-title" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</div>
          <div class="tg-file-sub">${item.formatted_size || ''}</div>
        </div>
        <div class="tg-file-download-btn">⬇️</div>
      `;
      bubble.appendChild(fileCard);
    }

    // Bottom Meta (Time + Double Checkmarks)
    const meta = document.createElement('div');
    meta.className = 'tg-bubble-meta';
    const timeStr = formatTime(item.timestamp);
    meta.innerHTML = `
      <span>${timeStr}</span>
      ${isOutgoing ? '<span class="tg-checkmarks">✓✓</span>' : ''}
    `;
    bubble.appendChild(meta);

    row.appendChild(bubble);
    return row;
  }

  // Send Text Message
  async function sendTextMessage() {
    const text = textInput.value.trim();
    if (!text) return;

    try {
      textInput.disabled = true;
      btnSend.disabled = true;

      const res = await fetch('/api/send/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          device: deviceName
        })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: 'Failed to send' }));
        throw new Error(errData.detail || 'Server error');
      }

      const data = await res.json();
      if (data && data.item) {
        if (!items.some(x => x.id === data.item.id)) {
          items.push(data.item);
          renderFeed();
          scrollToBottom();
        }
      }

      textInput.value = '';
      textInput.style.height = 'auto';
    } catch (err) {
      showToast('Error sending message', 'error');
    } finally {
      textInput.disabled = false;
      btnSend.disabled = false;
      textInput.focus();
    }
  }

  // Upload Files with Progress
  function uploadFiles(fileList, customCategory = null) {
    if (!fileList || fileList.length === 0) return;

    Array.from(fileList).forEach(file => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('sender', deviceName);
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

      xhr.open('POST', '/api/send/file', true);
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
      showToast('Microphone access denied', 'error');
    }
  }

  function stopAndSendRecording() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;

    mediaRecorder.onstop = () => {
      clearInterval(recordingTimerInterval);
      voiceOverlay.classList.add('hidden');

      const mimeType = mediaRecorder.mimeType || 'audio/webm';
      const ext = mimeType.includes('ogg') ? 'ogg' : (mimeType.includes('wav') ? 'wav' : 'webm');
      const audioBlob = new Blob(audioChunks, { type: mimeType });
      const audioFile = new File([audioBlob], `voice_note_${Date.now()}.${ext}`, { type: mimeType });

      uploadFiles([audioFile], 'audio');
    };

    mediaRecorder.stop();
  }

  function cancelRecording() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
    mediaRecorder.stop();
    clearInterval(recordingTimerInterval);
    voiceOverlay.classList.add('hidden');
    audioChunks = [];
  }

  // Delete Item
  async function deleteItem(id) {
    try {
      const res = await fetch(`/api/history/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      items = items.filter(x => x.id !== id);
      renderFeed();
    } catch (err) {
      showToast('Could not delete item', 'error');
    }
  }

  // Clear All History
  async function clearAllHistory() {
    if (!confirm('Are you sure you want to delete all messages?')) return;
    try {
      const res = await fetch('/api/history', { method: 'DELETE' });
      if (!res.ok) throw new Error('Clear failed');
      items = [];
      renderFeed();
      showToast('All messages deleted', 'info');
    } catch (err) {
      showToast('Could not clear messages', 'error');
    }
  }

  // Copy to Clipboard
  async function copyToClipboard(text, showNotification = true) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        textarea.remove();
      }
      if (showNotification) showToast('Copied to clipboard', 'success');
    } catch (e) {
      if (showNotification) showToast('Could not copy', 'error');
    }
  }

  // Lightbox Modal
  function openLightbox(url, title, downloadUrl) {
    currentRotation = 0;
    lightboxImage.style.transform = 'rotate(0deg)';
    lightboxImage.src = url;
    lightboxTitle.textContent = title || 'Photo';
    lightboxDownload.href = downloadUrl || url;
    lightboxDownload.setAttribute('download', title || 'photo');
    lightboxModal.classList.remove('hidden');
  }

  function closeLightbox() {
    lightboxModal.classList.add('hidden');
    lightboxImage.src = '';
  }

  // Event Listeners
  function setupEventListeners() {
    // Send message
    btnSend.addEventListener('click', sendTextMessage);
    textInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendTextMessage();
      }
    });

    textInput.addEventListener('input', () => {
      textInput.style.height = 'auto';
      textInput.style.height = `${Math.min(textInput.scrollHeight, 80)}px`;
    });

    // Attach file button
    btnAttachFile.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      uploadFiles(e.target.files);
      fileInput.value = '';
    });

    // Camera / Photo button
    btnOpenCamera.addEventListener('click', () => cameraInput.click());
    cameraInput.addEventListener('change', (e) => {
      uploadFiles(e.target.files);
      cameraInput.value = '';
    });

    // Quick Action Buttons
    if (btnQuickPhoto) btnQuickPhoto.addEventListener('click', () => cameraInput.click());
    if (btnQuickFile) btnQuickFile.addEventListener('click', () => fileInput.click());

    // Voice recording
    btnRecordVoice.addEventListener('click', startRecording);
    btnSendRecording.addEventListener('click', stopAndSendRecording);
    btnCancelRecording.addEventListener('click', cancelRecording);

    // Search Toggle
    tgBtnSearch.addEventListener('click', () => {
      tgSearchBar.classList.toggle('hidden');
      if (!tgSearchBar.classList.contains('hidden')) {
        searchInput.focus();
      }
    });

    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value;
      clearSearchBtn.classList.toggle('hidden', !searchQuery);
      renderFeed();
    });

    clearSearchBtn.addEventListener('click', () => {
      searchInput.value = '';
      searchQuery = '';
      clearSearchBtn.classList.add('hidden');
      renderFeed();
    });

    // Sound toggle
    btnToggleSound.addEventListener('click', () => {
      isSoundEnabled = !isSoundEnabled;
      localStorage.setItem('airlink_sound', isSoundEnabled);
      soundIcon.textContent = isSoundEnabled ? '🔔' : '🔕';
      showToast(isSoundEnabled ? 'Sound alerts on' : 'Sound alerts off', 'info');
      if (isSoundEnabled) playNotificationSound();
    });

    // Auto-copy toggle
    btnToggleAutoCopy.addEventListener('click', () => {
      isAutoCopyEnabled = !isAutoCopyEnabled;
      localStorage.setItem('airlink_autocopy', isAutoCopyEnabled);
      autoCopyIcon.textContent = isAutoCopyEnabled ? '📋' : '📑';
      showToast(isAutoCopyEnabled ? 'Auto-copy enabled' : 'Auto-copy disabled', 'info');
    });

    // QR Modal
    const openQr = () => {
      fetchSystemInfo();
      qrModal.classList.remove('hidden');
    };
    btnQrModal.addEventListener('click', openQr);
    btnCloseQrModal.addEventListener('click', () => qrModal.classList.add('hidden'));
    qrModal.querySelector('.tg-modal-backdrop').addEventListener('click', () => qrModal.classList.add('hidden'));

    ipSelect.addEventListener('change', updateSelectedIP);
    btnCopyUrl.addEventListener('click', () => copyToClipboard(directUrlInput.value));

    // More dropdown menu
    btnMoreMenu.addEventListener('click', (e) => {
      e.stopPropagation();
      moreMenuDropdown.classList.toggle('show');
    });
    document.addEventListener('click', () => {
      moreMenuDropdown.classList.remove('show');
    });
    btnClearHistory.addEventListener('click', clearAllHistory);

    // Lightbox events
    lightboxClose.addEventListener('click', closeLightbox);
    lightboxModal.querySelector('.tg-lightbox-backdrop').addEventListener('click', closeLightbox);
    lightboxRotate.addEventListener('click', () => {
      currentRotation = (currentRotation + 90) % 360;
      lightboxImage.style.transform = `rotate(${currentRotation}deg)`;
    });

    // Fullscreen Drag & Drop
    window.addEventListener('dragover', (e) => {
      e.preventDefault();
      dragOverlay.classList.remove('hidden');
    });

    window.addEventListener('dragleave', (e) => {
      if (e.relatedTarget === null) dragOverlay.classList.add('hidden');
    });

    window.addEventListener('drop', (e) => {
      e.preventDefault();
      dragOverlay.classList.add('hidden');
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    });

    // Escape closes modals
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        qrModal.classList.add('hidden');
        closeLightbox();
      }
    });
  }

  // Register PWA Service Worker
  function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js').catch(() => {});
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  document.addEventListener('DOMContentLoaded', init);

})();
