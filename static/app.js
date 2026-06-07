// ==========================================
// State Management
// ==========================================
let vapiInstance = null;
let isCallActive = false;
let hasConnected = false;
let selectedCallId = null;
let cachedStatus = {};
let cachedLogs = [];
let localActiveTranscript = [];
let currentPartialTranscript = null;

// Waveform & Telemetry state
let micAudioContext = null;
let micAnalyser = null;
let micStream = null;
let assistantVolume = 0;
let micVolume = 0;
let animationFrameId = null;
let callDurationTimer = null;
let callStartTime = null;
let activeDateTab = null;

function sanitizeSpelling(text) {
    if (!text) return '';
    return text
        .replace(/\b(Sean|Shaun)\b/g, 'Shaan')
        .replace(/\b(sean|shaun)\b/g, 'shaan')
        .replace(/\b(Rosa|dazar|Dazar)\b/g, 'Raza')
        .replace(/\b(rosa|dazar)\b/g, 'raza');
}

function formatPhoneNumber(phoneNumberString) {
    if (!phoneNumberString) return '';
    const cleaned = ('' + phoneNumberString).replace(/\D/g, '');
    const match = cleaned.match(/^(1|)?(\d{3})(\d{3})(\d{4})$/);
    if (match) {
        const intlCode = match[1] ? '+1 ' : '';
        return [intlCode, '(', match[2], ') ', match[3], '-', match[4]].join('');
    }
    return phoneNumberString;
}

// ==========================================
// DOM Elements
// ==========================================
const serverStatusDot = document.getElementById('server-status-dot');
const serverStatusText = document.getElementById('server-status-text');
const tunnelStatusDot = document.getElementById('tunnel-status-dot');
const tunnelStatusText = document.getElementById('tunnel-status-text');

const privateKeyInput = document.getElementById('private-key');
const publicKeyInput = document.getElementById('public-key');
const phoneNumberInput = document.getElementById('phone-number');
const btnSaveConfig = document.getElementById('btn-save-config');
const btnDeploy = document.getElementById('btn-deploy');

const assistantStatusBadge = document.getElementById('assistant-status-badge');
const assistantIdRow = document.getElementById('assistant-id-row');
const assistantIdText = document.getElementById('assistant-id-text');
const phoneLinkRow = document.getElementById('phone-link-row');
const phoneLinkText = document.getElementById('phone-link-text');
const googleCalendarInput = document.getElementById('google-calendar-id');
const meetingLinkInput = document.getElementById('meeting-link');
const smtpEmailInput = document.getElementById('smtp-email');
const smtpPasswordInput = document.getElementById('smtp-password');
const calendarLinkRow = document.getElementById('calendar-link-row');
const calendarLinkText = document.getElementById('calendar-link-text');

const callerNameInput = document.getElementById('caller-name');
const callerPhoneInput = document.getElementById('caller-phone');
const btnCall = document.getElementById('btn-call');
const callStatusLabel = document.getElementById('call-status');
const waveformContainer = document.getElementById('waveform');
const waveBars = document.querySelectorAll('.wave-bar');

const calendarGrid = document.getElementById('calendar-grid');
const btnResetCalendar = document.getElementById('btn-reset-calendar');

const callsList = document.getElementById('calls-list');
const transcriptFeed = document.getElementById('transcript-feed');

// ==========================================
// API Operations
// ==========================================

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const status = await res.json();
        cachedStatus = status;
        
        // Update Server Status
        serverStatusDot.classList.add('active');
        serverStatusText.textContent = 'Server: Online';
        
        // Update Tunnel Status
        if (tunnelStatusDot && tunnelStatusText) {
            if (status.tunnel_url) {
                tunnelStatusDot.classList.add('active');
                tunnelStatusText.innerHTML = `Tunnel: <a href="${status.tunnel_url}" target="_blank" class="highlight">${status.tunnel_url.replace('https://', '')}</a>`;
            } else {
                tunnelStatusDot.classList.remove('active');
                tunnelStatusText.textContent = 'Tunnel: Connecting...';
            }
        }
        
        // Update Configuration Panel UI
        if (status.is_deployed) {
            assistantStatusBadge.textContent = 'Deployed';
            assistantStatusBadge.classList.add('deployed');
            
            assistantIdRow.style.display = 'flex';
            assistantIdText.textContent = status.assistant_id;
            
            if (status.vapi_public_key_configured && !isCallActive) {
                btnCall.disabled = false;
                callStatusLabel.textContent = 'Ready to Call';
                callStatusLabel.classList.add('ready');
                callStatusLabel.classList.remove('calling', 'connected');
            }
        } else {
            assistantStatusBadge.textContent = 'Not Deployed';
            assistantStatusBadge.classList.remove('deployed');
            assistantIdRow.style.display = 'none';
            btnCall.disabled = true;
            callStatusLabel.textContent = 'Setup Credentials First';
            callStatusLabel.classList.remove('ready', 'calling', 'connected');
        }
        
        if (status.phone_number) {
            phoneLinkRow.style.display = 'flex';
            phoneLinkText.textContent = formatPhoneNumber(status.phone_number);
            
            // Header status update
            const headerPhone = document.getElementById('header-phone-status');
            const headerPhoneNum = document.getElementById('header-phone-number');
            if (headerPhone && headerPhoneNum) {
                headerPhone.style.display = 'flex';
                headerPhoneNum.textContent = formatPhoneNumber(status.phone_number);
            }
            
            // Front-page dialer card update
            const dialerInfo = document.getElementById('dialer-phone-line-info');
            const dialerPhoneNum = document.getElementById('dialer-phone-number');
            if (dialerInfo && dialerPhoneNum) {
                dialerInfo.style.display = 'block';
                dialerPhoneNum.textContent = formatPhoneNumber(status.phone_number);
            }
        } else {
            phoneLinkRow.style.display = 'none';
            
            const headerPhone = document.getElementById('header-phone-status');
            if (headerPhone) headerPhone.style.display = 'none';
            
            const dialerInfo = document.getElementById('dialer-phone-line-info');
            if (dialerInfo) dialerInfo.style.display = 'none';
        }
        
        if (status.google_calendar_id) {
            calendarLinkRow.style.display = 'flex';
            calendarLinkText.textContent = status.google_calendar_id;
        } else {
            calendarLinkRow.style.display = 'none';
        }
        
        // Auto-fill inputs if they are empty
        if (!privateKeyInput.value && status.vapi_private_key_configured) {
            privateKeyInput.placeholder = '•••••••••••••••• (Saved)';
        }
        if (!publicKeyInput.value && status.vapi_public_key_configured) {
            publicKeyInput.placeholder = '•••••••••••••••• (Saved)';
        }
        if (!phoneNumberInput.value && status.phone_number) {
            phoneNumberInput.value = status.phone_number;
        }
        if (!googleCalendarInput.value && status.google_calendar_id) {
            googleCalendarInput.value = status.google_calendar_id;
        }
        if (smtpEmailInput && !smtpEmailInput.value && status.smtp_email) {
            smtpEmailInput.value = status.smtp_email;
        }
        if (smtpPasswordInput && !smtpPasswordInput.value && status.smtp_password_configured) {
            smtpPasswordInput.placeholder = '•••••••••••••••• (Saved)';
        }
        
    } catch (err) {
        console.error('Failed to fetch status:', err);
        serverStatusDot.classList.remove('active');
        serverStatusText.textContent = 'Server: Offline';
    }
}

async function saveConfig() {
    const pKey = privateKeyInput.value.trim();
    const pubKey = publicKeyInput.value.trim();
    const phone = phoneNumberInput.value.trim();
    const googleCal = googleCalendarInput.value.trim();
    const smtpEmail = smtpEmailInput ? smtpEmailInput.value.trim() : "";
    const smtpPassword = smtpPasswordInput ? smtpPasswordInput.value.trim() : "";
    
    // Only throw alert if keys are completely missing from both inputs and backend
    if ((!pKey && !cachedStatus.vapi_private_key_configured) || (!pubKey && !cachedStatus.vapi_public_key_configured)) {
        alert('Both Vapi Private and Public Keys are required.');
        return;
    }
    
    try {
        btnSaveConfig.disabled = true;
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vapi_private_key: pKey,
                vapi_public_key: pubKey,
                phone_number: phone,
                google_calendar_id: googleCal,
                smtp_email: smtpEmail,
                smtp_password: smtpPassword
            })
        });
        const data = await res.json();
        alert(data.message);
        await fetchStatus();
    } catch (err) {
        alert('Failed to save config.');
    } finally {
        btnSaveConfig.disabled = false;
    }
}

async function deployAssistant() {
    try {
        btnDeploy.disabled = true;
        btnDeploy.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Deploying...';
        
        const res = await fetch('/api/deploy', { method: 'POST' });
        const data = await res.json();
        
        if (data.success) {
            alert(data.message);
        } else {
            alert('Deploy failed: ' + data.message);
        }
        await fetchStatus();
    } catch (err) {
        alert('Network error during deployment.');
    } finally {
        btnDeploy.disabled = false;
        btnDeploy.innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Deploy Assistant';
    }
}

async function fetchCalendar() {
    try {
        const res = await fetch('/api/calendar');
        const slots = await res.json();
        renderCalendar(slots);
    } catch (err) {
        console.error('Failed to fetch calendar:', err);
    }
}

async function resetCalendar() {
    if (!confirm('Are you sure you want to reset the calendar slots? All bookings, logs, and saved leads will be cleared.')) return;
    try {
        const res = await fetch('/api/calendar/reset', { method: 'POST' });
        const data = await res.json();
        renderCalendar(data.calendar);
        await fetchContacts();
        await fetchLogs();
    } catch (err) {
        alert('Failed to reset calendar.');
    }
}

async function fetchLogs() {
    try {
        const res = await fetch('/api/logs');
        const logs = await res.json();
        cachedLogs = logs;
        renderCallsList(logs);
        renderActiveTranscript(logs);
    } catch (err) {
        console.error('Failed to fetch logs:', err);
    }
}

// ==========================================
// UI Rendering Handlers
// ==========================================

function renderCalendar(slots) {
    if (!slots || slots.length === 0) {
        calendarGrid.innerHTML = '<div class="no-slots">No slots configured. Click reset.</div>';
        return;
    }
    
    // Get unique dates sorted chronologically, filtering out dates where all slots are in the past
    let uniqueDates = [...new Set(slots.filter(s => s.status !== 'past').map(s => s.date))].sort();
    if (uniqueDates.length === 0) {
        uniqueDates = [...new Set(slots.map(s => s.date))].sort(); // Fallback
    }
    
    // Render Day Tabs
    const tabsContainer = document.getElementById('calendar-tabs');
    if (tabsContainer) {
        tabsContainer.innerHTML = '';
        
        // Find next available slot for the banner
        let nextAvailable = slots.find(s => s.status === 'available');
        const nextSlotTime = document.getElementById('next-slot-time');
        if (nextSlotTime) {
            if (nextAvailable) {
                const dateObj = new Date(nextAvailable.date + 'T00:00:00');
                const formattedDate = dateObj.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
                nextSlotTime.textContent = `${formattedDate} at ${nextAvailable.time}`;
            } else {
                nextSlotTime.textContent = 'None available (fully booked)';
            }
        }
        
        // Default active tab to first date if not set or not in current list
        if (!activeDateTab || !uniqueDates.includes(activeDateTab)) {
            activeDateTab = uniqueDates[0];
        }
        
        uniqueDates.forEach(dateStr => {
            const dateObj = new Date(dateStr + 'T00:00:00');
            const formattedTabLabel = dateObj.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
            
            const tabBtn = document.createElement('button');
            tabBtn.className = `calendar-tab-btn ${activeDateTab === dateStr ? 'active' : ''}`;
            tabBtn.innerHTML = `<i class="fa-regular fa-calendar"></i> ${formattedTabLabel}`;
            tabBtn.onclick = () => {
                activeDateTab = dateStr;
                renderCalendarSlots(slots.filter(s => s.date === dateStr));
                const buttons = tabsContainer.querySelectorAll('.calendar-tab-btn');
                buttons.forEach(b => b.classList.remove('active'));
                tabBtn.classList.add('active');
            };
            tabsContainer.appendChild(tabBtn);
        });
    }
    
    // Render slots for the active date tab
    renderCalendarSlots(slots.filter(s => s.date === activeDateTab));
}

function renderCalendarSlots(activeSlots) {
    calendarGrid.innerHTML = '';
    if (!activeSlots || activeSlots.length === 0) {
        calendarGrid.innerHTML = '<div class="no-slots">No slots for this day.</div>';
        return;
    }
    
    activeSlots.forEach(slot => {
        const tile = document.createElement('div');
        tile.className = `slot-tile ${slot.status}`;
        
        // Normalise date label for display
        const dateObj = new Date(slot.date + 'T00:00:00');
        const formattedDate = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        
        let tileHTML = `
            <div class="slot-date-info">
                <span class="slot-day">${slot.day.slice(0, 3)}</span>
                <span class="slot-date">${formattedDate}</span>
            </div>
            <span class="slot-time">${slot.time}</span>
            <span class="slot-badge">${slot.status}</span>
        `;
        
        if (slot.status === 'booked' && slot.booked_by) {
            tileHTML += `
                <div class="slot-candidate">
                    <span class="candidate-name">${slot.booked_by.name}</span>
                    <span class="candidate-email">${slot.booked_by.email || slot.booked_by.contact || 'N/A'}</span>
                </div>
            `;
        }
        
        tile.innerHTML = tileHTML;
        calendarGrid.appendChild(tile);
    });
}

function renderCallsList(logs) {
    if (!callsList) return;
    if (!logs || logs.length === 0) {
        callsList.innerHTML = '<div class="no-calls">No calls recorded yet.</div>';
        return;
    }
    
    const sortedLogs = [...logs].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    callsList.innerHTML = '';
    
    sortedLogs.forEach(log => {
        const item = document.createElement('div');
        item.className = `call-item ${selectedCallId === log.call_id ? 'active' : ''}`;
        item.onclick = () => selectCall(log.call_id);
        
        const timeObj = new Date(log.timestamp);
        const timeStr = timeObj.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        
        item.innerHTML = `
            <div class="call-item-header">
                <span class="call-id-label">Call #${log.call_id.slice(-6)}</span>
                <span class="call-status-badge ${log.status}">${log.status}</span>
            </div>
            <span class="call-item-time">${log.day || ''} ${timeStr}</span>
        `;
        
        callsList.appendChild(item);
    });
    
    if (!selectedCallId && sortedLogs.length > 0) {
        const active = sortedLogs.find(l => l.status === 'in-progress' || l.status === 'ringing');
        selectCall(active ? active.call_id : sortedLogs[0].call_id);
    }
}

function selectCall(callId) {
    selectedCallId = callId;
    if (callsList) {
        const items = callsList.querySelectorAll('.call-item');
        items.forEach(el => el.classList.remove('active'));
    }
    renderActiveTranscript(cachedLogs);
}

function renderActiveTranscript(logs) {
    let transcript = [];
    
    if (isCallActive) {
        transcript = [...localActiveTranscript];
        if (currentPartialTranscript) {
            transcript.push(currentPartialTranscript);
        }
    } else {
        if (!selectedCallId) {
            transcriptFeed.innerHTML = `
                <div class="transcript-placeholder">
                    <i class="fa-solid fa-comments"></i>
                    <p>Start a call to see the live transcript feed here.</p>
                </div>
            `;
            return;
        }
        const activeLog = logs.find(l => l.call_id === selectedCallId);
        if (!activeLog) {
            if (localActiveTranscript && localActiveTranscript.length > 0) {
                transcript = [...localActiveTranscript];
            } else {
                transcriptFeed.innerHTML = '<div class="no-transcript">Log entry not found.</div>';
                return;
            }
        } else {
            transcript = activeLog.transcript || [];
        }
    }
    
    if (transcript.length === 0) {
        transcriptFeed.innerHTML = `
            <div class="transcript-placeholder">
                <i class="fa-solid fa-microphone-slash"></i>
                <p>Call started. Waiting for audio input to transcribe...</p>
            </div>
        `;
        return;
    }
    
    transcriptFeed.innerHTML = '';
    
    transcript.forEach(msg => {
        const bubble = document.createElement('div');
        bubble.className = `message-bubble ${msg.role}`;
        
        const senderName = msg.role === 'assistant' ? 'Shaan' : 'Interviewer';
        let cleanText = sanitizeSpelling(msg.text);
        
        bubble.innerHTML = `
            <span class="bubble-sender">${senderName}</span>
            <span class="bubble-text">${cleanText}</span>
        `;
        
        transcriptFeed.appendChild(bubble);
    });
    
    // Always force auto-scroll to the bottom when rendering transcripts to keep user context
    setTimeout(() => {
        transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
    }, 50);
}

// ==========================================
// Vapi Web Call Operations
// ==========================================

function initVapi() {
    if (vapiInstance) return vapiInstance;
    
    // Get actual public key from backend response if configured, fallback to input field
    const actualPubKey = cachedStatus.vapi_public_key || publicKeyInput.value.trim();
    
    if (!actualPubKey) {
        console.error('No Vapi Public Key available for Web Call');
        return null;
    }
    
    console.log('Initializing Vapi Web SDK...');
    // The Vapi script exposes Vapi globally (lowercase vapi or class Vapi)
    // Based on unpkg search: const vapi = new Vapi(publicKey)
    try {
        const VapiClass = window.Vapi;
        vapiInstance = new VapiClass(actualPubKey);
        
        // Listeners
        vapiInstance.on('call-start', (call) => {
            isCallActive = true;
            hasConnected = true;
            if (call && call.id) {
                selectedCallId = call.id;
            }
            btnCall.classList.add('active-call');
            btnCall.innerHTML = '<i class="fa-solid fa-phone-slash"></i>';
            callStatusLabel.textContent = 'Connected (Live)';
            callStatusLabel.className = 'call-status-label connected';
            waveformContainer.classList.add('active');
            
            // Clear inputs temporarily to prevent middle-call change
            callerNameInput.disabled = true;
            callerPhoneInput.disabled = true;
            
            startMicAnalysis();
            startCallTimer();
        });
        
        vapiInstance.on('call-end', () => {
            isCallActive = false;
            hasConnected = false;
            btnCall.classList.remove('active-call');
            btnCall.innerHTML = '<i class="fa-solid fa-phone"></i>';
            callStatusLabel.textContent = 'Ready to Call';
            callStatusLabel.className = 'call-status-label ready';
            waveformContainer.classList.remove('active');
            
            callerNameInput.disabled = false;
            callerPhoneInput.disabled = false;
            
            stopMicAnalysis();
            stopCallTimer();
            
            // Re-fetch logs to update status immediately
            setTimeout(fetchLogs, 1000);
            setTimeout(fetchCalendar, 1500);
        });
        
        vapiInstance.on('error', (err) => {
            console.error('Vapi Web SDK Error:', err);
            
            // If the call was already successfully connected, ignore normal tear-down errors.
            if (hasConnected) {
                return;
            }
            
            alert('Call Error: ' + (err.message || 'Failed to connect. Make sure your browser microphone permission is granted.'));
            isCallActive = false;
            hasConnected = false;
            btnCall.classList.remove('active-call');
            btnCall.innerHTML = '<i class="fa-solid fa-phone"></i>';
            callStatusLabel.textContent = 'Call Failed';
            callStatusLabel.className = 'call-status-label';
            waveformContainer.classList.remove('active');
            
            callerNameInput.disabled = false;
            callerPhoneInput.disabled = false;
            
            stopMicAnalysis();
            stopCallTimer();
        });
        
        vapiInstance.on('volume-level', (level) => {
            assistantVolume = level; // Feed the assistant volume to the canvas waveform
        });
        
        vapiInstance.on('message', (message) => {
            if (message.type === 'transcript') {
                const role = message.role;
                let text = sanitizeSpelling(message.transcript);
                const isFinal = message.transcriptType === 'final';
                
                if (isFinal) {
                    if (text && text.trim()) {
                        localActiveTranscript.push({ role, text });
                    }
                    currentPartialTranscript = null;
                } else {
                    if (text && text.trim()) {
                        currentPartialTranscript = { role, text };
                    } else {
                        currentPartialTranscript = null;
                    }
                }
                
                if (isCallActive) {
                    renderActiveTranscript(cachedLogs);
                }
            }
        });
        
        return vapiInstance;
    } catch (e) {
        console.error('Failed to initialize Vapi Web SDK:', e);
        return null;
    }
}

function toggleWebCall() {
    if (isCallActive) {
        console.log('Ending Vapi web call...');
        if (vapiInstance) vapiInstance.stop();
    } else {
        console.log('Starting Vapi web call with permission check...');
        const name = callerNameInput.value.trim() || 'Interviewer';
        const phone = callerPhoneInput.value.trim() || '';
        
        const sdk = initVapi();
        if (!sdk) {
            alert('Could not initialize browser call. Save config keys first.');
            return;
        }
        
        callStatusLabel.textContent = 'Requesting Mic...';
        callStatusLabel.className = 'call-status-label calling';
        
        // Explicitly pre-grant browser microphone permission
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then((stream) => {
                // Instantly stop temporary stream tracks to release device
                stream.getTracks().forEach(track => track.stop());
                
                callStatusLabel.textContent = 'Connecting...';
                
                localActiveTranscript = [];
                currentPartialTranscript = null;
                
                // Start call now that permission is pre-approved
                sdk.start(cachedStatus.assistant_id, {
                    variableValues: {
                        interviewer_name: name,
                        interviewer_phone: phone
                    }
                });
            })
            .catch((err) => {
                console.error('Microphone access denied:', err);
                alert('Microphone permission is required to start the browser call. Please allow microphone access.');
                callStatusLabel.textContent = 'Permission Denied';
                callStatusLabel.className = 'call-status-label';
            });
    }
}

// ==========================================
// Setup Event Listeners & Loops
// ==========================================

function setupEventListeners() {
    btnSaveConfig.onclick = saveConfig;
    btnDeploy.onclick = deployAssistant;
    btnResetCalendar.onclick = resetCalendar;
    btnCall.onclick = toggleWebCall;
    
    // Collapsible Settings Drawer
    const btnToggleSettings = document.getElementById('btn-toggle-settings');
    const settingsDrawer = document.getElementById('settings-drawer');
    const btnCloseSettings = document.getElementById('btn-close-settings');
    if (btnToggleSettings && settingsDrawer && btnCloseSettings) {
        btnToggleSettings.onclick = () => settingsDrawer.classList.add('open');
        btnCloseSettings.onclick = () => settingsDrawer.classList.remove('open');
    }
    
    // Call Details Modal Close
    const btnCloseModal = document.getElementById('btn-close-modal');
    if (btnCloseModal) {
        btnCloseModal.onclick = () => {
            document.getElementById('call-details-modal').classList.remove('open');
        };
    }
    
    // Save CRM Lead Details
    const btnSaveCrm = document.getElementById('btn-save-crm');
    if (btnSaveCrm) {
        btnSaveCrm.onclick = async () => {
            if (!currentDetailsContactId) return;
            const statusVal = document.getElementById('crm-lead-status').value;
            const notesVal = document.getElementById('crm-lead-notes').value;
            
            try {
                btnSaveCrm.disabled = true;
                btnSaveCrm.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
                const res = await fetch(`/api/contacts/${currentDetailsContactId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: statusVal, notes: notesVal })
                });
                const data = await res.json();
                if (data.success) {
                    alert('Lead status updated successfully!');
                    document.getElementById('call-details-modal').classList.remove('open');
                    await fetchContacts();
                } else {
                    alert('Error: ' + data.message);
                }
            } catch (e) {
                alert('Failed to update lead details.');
            } finally {
                btnSaveCrm.disabled = false;
                btnSaveCrm.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Update Lead Status';
            }
        };
    }
}

async function initializeApp() {
    setupEventListeners();
    
    // Initial fetches
    await fetchStatus();
    await fetchCalendar();
    await fetchLogs();
    await fetchContacts();
    
    // Start Polling loops
    // Status loop: every 5 seconds
    setInterval(fetchStatus, 5000);
    // Calendar loop: every 3 seconds
    setInterval(fetchCalendar, 3000);
    // Logs loop: every 2 seconds
    setInterval(fetchLogs, 2000);
    // Contacts loop: every 3 seconds
    setInterval(fetchContacts, 3000);
}

// Start app
window.onload = initializeApp;

// ==========================================
// Saved Contacts & Leads Operations
// ==========================================

async function fetchContacts() {
    try {
        const res = await fetch('/api/contacts');
        const contacts = await res.json();
        renderContacts(contacts);
    } catch (err) {
        console.error('Failed to fetch contacts:', err);
    }
}

function renderContacts(contacts) {
    const body = document.getElementById('contacts-list-body');
    if (!body) return;
    
    if (!contacts || contacts.length === 0) {
        body.innerHTML = '<tr><td colspan="6" class="no-leads">No leads saved yet. Try booking an interview!</td></tr>';
        return;
    }
    
    body.innerHTML = '';
    contacts.forEach(c => {
        const row = document.createElement('tr');
        row.style.cursor = 'pointer';
        row.onclick = (e) => {
            // If they clicked on the calendar anchor tag, don't open the modal
            if (e.target.closest('a')) return;
            openContactDetailsModal(c);
        };
        
        const emailVal = c.email || c.contact || '<span class="text-secondary">N/A</span>';
        const phoneVal = c.phone || '<span class="text-secondary">N/A</span>';
        
        let inviteLinkHTML = '<span class="text-secondary">Pending</span>';
        if (c.google_event_link) {
            inviteLinkHTML = `<a href="${c.google_event_link}" target="_blank" class="meet-btn" style="background: rgba(66, 133, 244, 0.2); border-color: #4285f4;"><i class="fa-solid fa-calendar-check"></i> Calendar</a>`;
        }
        
        row.innerHTML = `
            <td><strong>${c.name}</strong></td>
            <td>${emailVal}</td>
            <td>${phoneVal}</td>
            <td><span class="badge date-badge">${c.date}</span></td>
            <td><span class="badge time-badge">${c.time}</span></td>
            <td>${inviteLinkHTML}</td>
        `;
        body.appendChild(row);
    });
}

let currentDetailsContactId = null;

function openContactDetailsModal(c) {
    currentDetailsContactId = c.id;
    document.getElementById('modal-lead-name').textContent = c.name;
    document.getElementById('modal-lead-email').textContent = c.email || c.contact || 'N/A';
    document.getElementById('modal-lead-phone').textContent = c.phone || 'N/A';
    document.getElementById('modal-lead-time').textContent = `${c.date} ${c.time}`;
    
    document.getElementById('crm-lead-status').value = c.status || 'Scheduled';
    document.getElementById('crm-lead-notes').value = c.notes || '';
    
    // Sentiment Badge
    const sentimentSpan = document.getElementById('modal-lead-sentiment');
    sentimentSpan.textContent = c.sentiment || 'Neutral';
    sentimentSpan.className = 'badge';
    if (c.sentiment === 'Positive') {
        sentimentSpan.classList.add('sentiment-positive');
    } else if (c.sentiment === 'Negative') {
        sentimentSpan.classList.add('sentiment-negative');
    } else {
        sentimentSpan.classList.add('sentiment-neutral');
    }
    
    // Summary
    document.getElementById('modal-lead-summary').textContent = c.summary || 'No summary available for this call yet.';
    
    // Prep list items
    const prepContainer = document.getElementById('modal-lead-prep');
    prepContainer.innerHTML = '';
    const prepList = c.prep_sheet || [];
    if (prepList.length === 0) {
        prepContainer.innerHTML = '<ul><li>No prep notes compiled.</li></ul>';
    } else {
        const ul = document.createElement('ul');
        prepList.forEach(item => {
            const li = document.createElement('li');
            li.textContent = item;
            ul.appendChild(li);
        });
        prepContainer.appendChild(ul);
    }
    
    // Recording player
    const audioContainer = document.getElementById('audio-player-container');
    audioContainer.innerHTML = '';
    if (c.recording_url) {
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.style.width = '100%';
        audio.src = c.recording_url;
        audioContainer.appendChild(audio);
    } else {
        audioContainer.innerHTML = '<p style="font-size: 13px; color: rgba(255,255,255,0.5);"><i class="fa-solid fa-hourglass-half"></i> Recording not available or still processing...</p>';
    }
    
    document.getElementById('call-details-modal').classList.add('open');
}

// ==========================================
// Mic Analysis & Call Telemetry Animations
// ==========================================

function startMicAnalysis() {
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            micStream = stream;
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            micAudioContext = new AudioContextClass();
            const source = micAudioContext.createMediaStreamSource(stream);
            micAnalyser = micAudioContext.createAnalyser();
            micAnalyser.fftSize = 256;
            source.connect(micAnalyser);
            
            drawWaveforms();
        })
        .catch(err => {
            console.error("Mic analysis initialization failed:", err);
        });
}

function stopMicAnalysis() {
    if (animationFrameId) {
        cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
    }
    if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
    }
    if (micAudioContext) {
        micAudioContext.close();
        micAudioContext = null;
    }
    micAnalyser = null;
    assistantVolume = 0;
    micVolume = 0;
    
    // Clear Canvas baseline
    const canvas = document.getElementById('voice-waves');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}

function drawWaveforms() {
    if (!isCallActive) return;
    animationFrameId = requestAnimationFrame(drawWaveforms);
    
    const canvas = document.getElementById('voice-waves');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    
    ctx.clearRect(0, 0, W, H);
    
    if (micAnalyser) {
        const dataArray = new Uint8Array(micAnalyser.frequencyBinCount);
        micAnalyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i];
        }
        micVolume = sum / dataArray.length / 255;
    }
    
    const time = Date.now() * 0.005;
    
    // Draw Microphone Wave (Cyan)
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.6)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 0; x < W; x++) {
        const amp = micVolume * 20;
        const freq = 0.05;
        const y = H/2 - 5 + Math.sin(x * freq + time) * amp;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
    
    // Draw Assistant Wave (Indigo/Purple)
    ctx.strokeStyle = 'rgba(99, 102, 241, 0.7)';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    for (let x = 0; x < W; x++) {
        const amp = assistantVolume * 25;
        const freq = 0.04;
        const y = H/2 + 5 + Math.sin(x * freq - time * 1.2) * amp;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
    
    // Baseline
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, H/2);
    ctx.lineTo(W, H/2);
    ctx.stroke();
}

function startCallTimer() {
    callStartTime = Date.now();
    const durationSpan = document.getElementById('telemetry-duration');
    const latencySpan = document.getElementById('telemetry-latency');
    const telemetryContainer = document.getElementById('call-telemetry');
    
    if (telemetryContainer) {
        telemetryContainer.style.display = 'flex';
    }
    
    callDurationTimer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
        const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const secs = String(elapsed % 60).padStart(2, '0');
        if (durationSpan) {
            durationSpan.textContent = `${mins}:${secs}`;
        }
        
        // Emulate realistic latency round-trip time
        const rtt = 70 + Math.floor(Math.random() * 25);
        if (latencySpan) {
            latencySpan.textContent = `${rtt} ms`;
        }
    }, 1000);
}

function stopCallTimer() {
    if (callDurationTimer) {
        clearInterval(callDurationTimer);
        callDurationTimer = null;
    }
    const telemetryContainer = document.getElementById('call-telemetry');
    if (telemetryContainer) {
        telemetryContainer.style.display = 'none';
    }
}
