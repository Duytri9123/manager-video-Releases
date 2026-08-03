// Script for DTRouter-like AI Providers view in Video Tool client
(function() {
    let localConfig = {};
    let activeProviderId = null;
    let editingConnectionId = null; // null means adding a new connection
    const modelTestStatuses = {};

    // Catalog definition
    const PROVIDERS_CATALOG = {
        // OAuth Providers
        antigravity: { 
            id: "antigravity", name: "Antigravity", category: "oauth", logo: "antigravity.png", color: "#F59E0B", textIcon: "AG", desc: "Google Gemini / Antigravity API Connection", authType: "API Key", signup: "https://aistudio.google.com"
        },
        codex: { 
            id: "codex", name: "OpenAI Codex", category: "oauth", logo: "codex.png", color: "#3B82F6", textIcon: "CX", desc: "OpenAI Codex API Connection", authType: "API Key", signup: "https://platform.openai.com"
        },
        xai: { id: "xai", name: "xAI (Grok)", category: "oauth", logo: "xai.png", color: "#1DA1F2", textIcon: "XA", desc: "xAI API Client / Web Token", authType: "OAuth", signup: "https://x.ai" },
        nanobanana: { id: "nanobanana", name: "Nano Banana", category: "oauth", logo: "nanobanana.png", color: "#FACC15", textIcon: "NB", desc: "Nano Banana AI proxy connection", authType: "OAuth", signup: "https://nanobanana.ai" },
        
        opencode: { id: "opencode", name: "OpenCode Free", category: "llm", logo: "opencode.png", color: "#E87040", textIcon: "OC", desc: "OpenCode AI Free Models API", authType: "API Key", signup: "https://opencode.ai", noAuth: true },
        kiro: { id: "kiro", name: "Kiro AI", category: "llm", logo: "kiro.png", color: "#FF6B35", textIcon: "KR", desc: "Kiro AI Free tier models", authType: "API Key", signup: "https://kiro.dev" },
        openrouter: { id: "openrouter", name: "OpenRouter", category: "llm", logo: "openrouter.png", color: "#F97316", textIcon: "OR", desc: "OpenRouter Free Models Gateway", authType: "API Key", signup: "https://openrouter.ai" },
        nvidia: { id: "nvidia", name: "NVIDIA NIM", category: "llm", logo: "nvidia.png", color: "#76B900", textIcon: "NV", desc: "NVIDIA NIM API Key", authType: "API Key", signup: "https://build.nvidia.com" },
        ollama: { id: "ollama", name: "Ollama Cloud", category: "llm", logo: "ollama.png", color: "#333333", textIcon: "OL", desc: "Ollama cloud models", authType: "API Key", signup: "https://ollama.com" },
        gemini: { id: "gemini", name: "Gemini", category: "llm", logo: "gemini.png", color: "#4285F4", textIcon: "GE", desc: "Google Gemini API Key", authType: "API Key", signup: "https://aistudio.google.com" },
        openai: { id: "openai", name: "OpenAI", category: "llm", logo: "openai.png", color: "#10A37F", textIcon: "OA", desc: "OpenAI API Key", authType: "API Key", signup: "https://platform.openai.com" },
        groq: { id: "groq", name: "Groq", category: "llm", logo: "groq.png", color: "#F55036", textIcon: "GQ", desc: "Groq Whisper + LLM API Key", authType: "API Key", signup: "https://console.groq.com" },
        deepseek: { id: "deepseek", name: "DeepSeek", category: "llm", logo: "deepseek.png", color: "#4D6BFE", textIcon: "DS", desc: "DeepSeek Chat API Key", authType: "API Key", signup: "https://platform.deepseek.com" },
        huggingface: { id: "huggingface", name: "HuggingFace", category: "llm", logo: "huggingface.png", color: "#FFD21E", textIcon: "HF", desc: "HuggingFace User Token", authType: "API Key", signup: "https://huggingface.co" },
        kimi: { id: "kimi", name: "Kimi", category: "llm", logo: "kimi.png", color: "#1E3A8A", textIcon: "KM", desc: "Moonshot Kimi API Key", authType: "API Key", signup: "https://platform.moonshot.cn" },

        // Speech & Voice Providers
        fptai: { id: "fptai", name: "FPT AI", category: "speech", logo: "fptai.png", color: "#F26522", textIcon: "FP", desc: "FPT AI TTS giọng Việt API Key", authType: "API Key", signup: "https://fpt.ai" },
        fishaudio: { id: "fishaudio", name: "Fish Audio", category: "speech", logo: "fishaudio.png", color: "#3B82F6", textIcon: "FA", desc: "Fish Audio TTS đa ngôn ngữ API Key", authType: "API Key", signup: "https://fish.audio" },
        deepgram: { id: "deepgram", name: "Deepgram", category: "speech", logo: "deepgram.png", color: "#13EF93", textIcon: "DG", desc: "Deepgram Speech AI API Key", authType: "API Key", signup: "https://deepgram.com" },
        elevenlabs: { id: "elevenlabs", name: "ElevenLabs", category: "speech", logo: "elevenlabs.png", color: "#6C47FF", textIcon: "EL", desc: "ElevenLabs TTS API Key", authType: "API Key", signup: "https://elevenlabs.io" },
        cartesia: { id: "cartesia", name: "Cartesia", category: "speech", logo: "cartesia.png", color: "#FF4F8B", textIcon: "CA", desc: "Cartesia Sonic TTS API Key", authType: "API Key", signup: "https://cartesia.ai" },
        playht: { id: "playht", name: "PlayHT", category: "speech", logo: "playht.png", color: "#00B4D8", textIcon: "PH", desc: "PlayHT voice generation API Key", authType: "API Key", signup: "https://play.ht" },
        inworld: { id: "inworld", name: "Inworld TTS", category: "speech", logo: "inworld.png", color: "#FF6B6B", textIcon: "IW", desc: "Inworld Character TTS API Key", authType: "API Key", signup: "https://inworld.ai" },
        minimax: { id: "minimax", name: "Minimax Coding", category: "speech", logo: "minimax.png", color: "#7C3AED", textIcon: "MM", desc: "Minimax TTS + LLM API Key", authType: "API Key", signup: "https://minimaxi.com" },
        "minimax-cn": { id: "minimax-cn", name: "Minimax (China)", category: "speech", logo: "minimax-cn.png", color: "#DC2626", textIcon: "MC", desc: "Minimax Chinese regional API Key", authType: "API Key", signup: "https://minimaxi.com" },
        hyperbolic: { id: "hyperbolic", name: "Hyperbolic", category: "speech", logo: "hyperbolic.png", color: "#00D4FF", textIcon: "HP", desc: "Hyperbolic Melo TTS API Key", authType: "API Key", signup: "https://hyperbolic.xyz" },
        assemblyai: { id: "assemblyai", name: "AssemblyAI", category: "speech", logo: "assemblyai.png", color: "#0062FF", textIcon: "AA", desc: "AssemblyAI ASR API Key", authType: "API Key", signup: "https://assemblyai.com" },

        // Web Search & Scrape Providers
        perplexity: { id: "perplexity", name: "Perplexity", category: "search", logo: "perplexity.png", color: "#20808D", textIcon: "PP", desc: "Perplexity Web Search API Key", authType: "API Key", signup: "https://perplexity.ai" },
        tavily: { id: "tavily", name: "Tavily", category: "search", logo: "tavily.png", color: "#5B21B6", textIcon: "TV", desc: "Tavily Search API Key", authType: "API Key", signup: "https://tavily.com" },
        "brave-search": { id: "brave-search", name: "Brave Search", category: "search", logo: "brave-search.png", color: "#FB542B", textIcon: "BR", desc: "Brave Web Search API Key", authType: "API Key", signup: "https://brave.com" },
        serper: { id: "serper", name: "Serper", category: "search", logo: "serper.png", color: "#4F46E5", textIcon: "SP", desc: "Google Search Serper API Key", authType: "API Key", signup: "https://serper.dev" },
        exa: { id: "exa", name: "Exa", category: "search", logo: "exa.png", color: "#2563EB", textIcon: "EX", desc: "Exa Neural Search API Key", authType: "API Key", signup: "https://exa.ai" },
        "google-pse": { id: "google-pse", name: "Google PSE", category: "search", logo: "google-pse.png", color: "#4285F4", textIcon: "GP", desc: "Google Programmable Search Engine ID & API Key", authType: "API Key", signup: "https://programmablesearchengine.google.com" },
        linkup: { id: "linkup", name: "Linkup", category: "search", logo: "linkup.png", color: "#0EA5E9", textIcon: "LK", desc: "Linkup Search API Key", authType: "API Key", signup: "https://linkup.ai" },
        searchapi: { id: "searchapi", name: "SearchAPI", category: "search", logo: "searchapi.png", color: "#0EA5A4", textIcon: "SA", desc: "SearchAPI Index Key", authType: "API Key", signup: "https://searchapi.io" },
        youcom: { id: "youcom", name: "You.com Search", category: "search", logo: "youcom.png", color: "#7C3AED", textIcon: "YC", desc: "You.com Search API Key", authType: "API Key", signup: "https://you.com" },
        firecrawl: { id: "firecrawl", name: "Firecrawl", category: "search", logo: "firecrawl.png", color: "#F59E0B", textIcon: "FC", desc: "Firecrawl Scrape API Key", authType: "API Key", signup: "https://firecrawl.dev" }
    };

    function log(msg) {
        console.log('[Providers Log]', msg);
        const out = document.getElementById('debug-log-output');
        if (out) {
            const div = document.createElement('div');
            div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
            out.appendChild(div);
            out.scrollTop = out.scrollHeight;
        }
    }

    function showErrorBanner(msg) {
        log('Error Banner shown: ' + msg);
        let banner = document.getElementById('providers-error-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'providers-error-banner';
            banner.className = 'p-4 mb-4 bg-rose-100 border border-rose-200 text-rose-800 rounded-xl text-xs whitespace-pre-wrap font-mono';
            const pageEl = document.getElementById('page-providers');
            if (pageEl) {
                pageEl.insertBefore(banner, pageEl.firstChild);
            }
        }
        banner.textContent = msg;
    }

    window.loadProvidersConfig = async function() {
        try {
            log('loadProvidersConfig initiated');
            log('Fetching local config...');
            const res = await fetch('/api/config');
            if (res.ok) {
                localConfig = await res.json();
                log('Local config fetched. providers key count: ' + Object.keys(localConfig.providers || {}).length);
                if (!localConfig.providers) {
                    localConfig.providers = {};
                }
                renderProvidersGrid();
                if (activeProviderId) {
                    renderProviderDetails();
                }
            } else {
                showErrorBanner('fetch /api/config failed with status ' + res.status);
            }
        } catch (e) {
            showErrorBanner('loadProvidersConfig Exception: ' + e.message + '\n' + e.stack);
        }
    };    function renderProvidersGrid() {
        try {
            log('renderProvidersGrid initiated');
            const oauthGrid = document.getElementById('oauth-grid');
            const llmGrid = document.getElementById('llm-grid');
            const speechGrid = document.getElementById('speech-grid');
            const searchGrid = document.getElementById('search-grid');
            if (!oauthGrid || !llmGrid || !speechGrid || !searchGrid) {
                log('Warning: One of grid elements not found in DOM!');
                return;
            }

            log('Clearing grid DOM elements...');
            oauthGrid.innerHTML = '';
            llmGrid.innerHTML = '';
            speechGrid.innerHTML = '';
            searchGrid.innerHTML = '';

            let oauthCount = 0;
            let llmCount = 0;
            let speechCount = 0;
            let searchCount = 0;

            Object.values(PROVIDERS_CATALOG).forEach(p => {
                const data = localConfig.providers[p.id] || { connections: [], strategy: 'fallback' };
                const connections = data.connections || [];
                const activeCount = connections.filter(c => c.enabled).length;

                // Generate status badge HTML
                let badgeHtml = '';
                if (p.noAuth) {
                    badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>Ready</span>`;
                } else if (activeCount > 0) {
                    badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>${activeCount} Connected</span>`;
                } else {
                    badgeHtml = `<span class="text-slate-450 dark:text-slate-500 text-[11px] font-medium">No connections</span>`;
                }

                const allDisabled = connections.length > 0 && connections.every(c => !c.enabled);
                if (allDisabled) {
                    badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-450 dark:text-slate-500 flex items-center gap-1">🚫 Disabled</span>`;
                }

                const card = document.createElement('div');
                card.className = `bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-850 p-4 shadow-xs hover:border-orange-500/40 hover:-translate-y-0.5 cursor-pointer transition-all duration-300 flex items-center justify-between ${allDisabled ? 'opacity-65' : ''}`;
                card.onclick = () => showDetailView(p.id);

                card.innerHTML = `
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="w-9 h-9 rounded-lg flex items-center justify-center p-1.5 bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-805 shrink-0">
                            <img class="w-full h-full object-contain rounded-md" src="/static/Images/providers/${p.logo}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" alt="">
                            <div class="hidden w-full h-full items-center justify-center rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-bold text-slate-500" style="display:none">${p.textIcon || p.name.slice(0,2).toUpperCase()}</div>
                        </div>
                        <div class="min-w-0">
                            <h3 class="font-bold text-xs text-slate-800 dark:text-slate-200 truncate">${p.name}</h3>
                            <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                                ${badgeHtml}
                            </div>
                        </div>
                    </div>
                    <div class="flex shrink-0 items-center gap-2" onclick="event.stopPropagation()">
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" ${p.noAuth || (!allDisabled && connections.length > 0) ? 'checked' : ''} onchange="${connections.length > 0 ? `toggleAllConnections('${p.id}', this.checked)` : `showDetailView('${p.id}')`}" class="sr-only peer">
                            <div class="w-7 h-4 bg-slate-200 dark:bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-350 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-orange-500"></div>
                        </label>
                    </div>
                `;

                if (p.category === 'oauth') {
                    oauthGrid.appendChild(card);
                    oauthCount++;
                } else if (p.category === 'llm') {
                    llmGrid.appendChild(card);
                    llmCount++;
                } else if (p.category === 'speech') {
                    speechGrid.appendChild(card);
                    speechCount++;
                } else if (p.category === 'search') {
                    searchGrid.appendChild(card);
                    searchCount++;
                }
            });
            log(`renderProvidersGrid completed. Rendered ${oauthCount} OAuth, ${llmCount} LLM, ${speechCount} Speech, ${searchCount} Search cards.`);
        } catch (err) {
            showErrorBanner('renderProvidersGrid Error: ' + err.message + '\n' + err.stack);
        }
    }

    window.showDetailView = function(providerId) {
        activeProviderId = providerId;
        document.getElementById('providers-list-view').classList.add('hidden');
        document.getElementById('providers-list-view').style.display = 'none';
        
        const details = document.getElementById('provider-details-view');
        details.classList.remove('hidden');
        details.style.display = 'block';

        renderProviderDetails();

        // Tự động kiểm tra ngay các kết nối đang bật (enabled) khi vừa vào trang
        setTimeout(() => {
            if (activeProviderId === providerId) {
                testConnectionsOneByOne(true);
            }
        }, 150);
    };

    window.showListView = function() {
        activeProviderId = null;
        document.getElementById('provider-details-view').classList.add('hidden');
        document.getElementById('provider-details-view').style.display = 'none';

        const list = document.getElementById('providers-list-view');
        list.classList.remove('hidden');
        list.style.display = 'block';

        loadProvidersConfig();
    };

    function renderProviderDetails() {
        try {
            const p = PROVIDERS_CATALOG[activeProviderId];
            if (!p) return;

            // Set Headers
            document.getElementById('detail-breadcrumb-icon').src = `/static/Images/providers/${p.logo}`;
            document.getElementById('detail-breadcrumb-name').textContent = p.name;
            document.getElementById('detail-provider-icon').src = `/static/Images/providers/${p.logo}`;
            document.getElementById('detail-provider-name').textContent = p.name;
            document.getElementById('detail-provider-signup').href = p.signup;

            const data = localConfig.providers[p.id] || { connections: [], strategy: 'fallback' };
            const connections = data.connections || [];
            document.getElementById('detail-connection-count').textContent = `${connections.length} connection${connections.length === 1 ? '' : 's'}`;

            // Strategy round-robin toggle
            const toggleRR = document.getElementById('toggle-round-robin');
            if (toggleRR) toggleRR.checked = (data.strategy === 'round-robin');

            // Risk / Warning notices
            const noticeEl = document.getElementById('detail-risk-notice');
            const noticeText = document.getElementById('detail-risk-text');
            if (p.riskNotice) {
                noticeEl.classList.remove('hidden');
                noticeEl.style.display = 'flex';
                noticeText.textContent = p.riskNotice;
            } else {
                noticeEl.classList.add('hidden');
                noticeEl.style.display = 'none';
            }

            // Render connection rows
            const rowsContainer = document.getElementById('connections-list-rows');
            rowsContainer.innerHTML = '';

            const headerActions = document.getElementById('connections-header-actions');
            const listHeader = document.getElementById('connections-list-header');
            const addBtnContainer = document.getElementById('connections-add-btn-container');
            const quotaCard = document.getElementById('detail-quota-tracker-card');

            if (p.noAuth) {
                if (headerActions) headerActions.style.display = 'none';
                if (listHeader) listHeader.style.display = 'none';
                if (addBtnContainer) addBtnContainer.style.display = 'none';
                if (quotaCard) quotaCard.style.display = 'none';
                rowsContainer.innerHTML = `
                    <div class="flex items-center gap-3 p-4 rounded-xl border border-emerald-500/20 bg-emerald-500/5 text-xs text-emerald-700 dark:text-emerald-400">
                        <div class="inline-flex items-center justify-center w-8 h-8 rounded-full bg-emerald-500/10 text-emerald-500 shrink-0">
                            <span class="material-symbols-outlined text-[18px]">lock_open</span>
                        </div>
                        <div class="flex-1">
                            <p class="text-sm font-semibold">No authentication required</p>
                            <p class="text-xs text-slate-500 dark:text-slate-455 mt-0.5">This provider is ready to use. Optionally route requests directly to bypass IP-based limits.</p>
                        </div>
                    </div>
                `;
            } else {
                if (headerActions) headerActions.style.display = 'flex';
                if (listHeader) listHeader.style.display = 'flex';
                if (addBtnContainer) addBtnContainer.style.display = 'block';
                if (quotaCard) quotaCard.style.display = 'none';

                if (connections.length === 0) {
                    rowsContainer.innerHTML = `
                        <div class="py-8 text-center text-slate-405 dark:text-slate-550 text-xs">
                            No connections yet. Click Add to create a new one.
                        </div>
                    `;
                } else {
                    connections.forEach((c, index) => {
                        const row = document.createElement('div');
                        row.className = `flex flex-col gap-2.5 px-3 py-3 border-b border-slate-50 dark:border-slate-850 hover:bg-slate-50/40 dark:hover:bg-slate-900/40 transition-all`;

                        // status color
                        let statusDot = 'bg-slate-400';
                        let statusText = 'disabled';
                        let statusClass = 'text-slate-450 dark:text-slate-555';
                        if (c.enabled) {
                            if (c.status === 'active') {
                                statusDot = 'bg-emerald-500';
                                statusText = 'active';
                                statusClass = 'text-emerald-600 dark:text-emerald-400 font-bold';
                            } else if (c.status === 'error') {
                                statusDot = 'bg-rose-500';
                                statusText = 'error';
                                statusClass = 'text-rose-600 dark:text-rose-400 font-bold';
                            } else if (c.status === 'testing') {
                                statusDot = 'bg-amber-500 animate-pulse';
                                statusText = 'testing';
                                statusClass = 'text-amber-500 font-bold';
                            } else {
                                statusDot = 'bg-slate-400';
                                statusText = c.status || 'untested';
                                statusClass = 'text-slate-500 font-medium';
                            }
                        }

                        row.innerHTML = `
                            <div class="flex items-center gap-3 w-full">
                                <input type="checkbox" data-conn-id="${c.id}" class="rounded connection-select-check">
                                
                                <!-- Sorting / ordering -->
                                <div class="flex flex-col gap-0.5 text-slate-400 dark:text-slate-600 ml-2">
                                    <span class="material-symbols-outlined text-base cursor-pointer hover:text-slate-600 dark:hover:text-slate-400 leading-none" onclick="moveConnection('${p.id}', '${c.id}', -1)">arrow_drop_up</span>
                                    <span class="material-symbols-outlined text-base cursor-pointer hover:text-slate-600 dark:hover:text-slate-400 leading-none" onclick="moveConnection('${p.id}', '${c.id}', 1)">arrow_drop_down</span>
                                </div>

                                <div class="flex items-center gap-2.5 ml-4 flex-1 min-w-0">
                                    <span class="material-symbols-outlined text-lg text-slate-400 dark:text-slate-50">${p.authType === 'OAuth' ? 'lock' : 'vpn_key'}</span>
                                    <div class="min-w-0">
                                        <span class="font-bold text-sm text-slate-800 dark:text-slate-200 truncate block">${c.name || 'Untitled Connection'}</span>
                                        <div class="flex items-center gap-1.5 mt-0.5">
                                            <span class="w-1.5 h-1.5 rounded-full ${statusDot}"></span>
                                            <span class="text-[9px] uppercase tracking-wider ${statusClass}">${c.enabled ? statusText : 'disabled'}</span>
                                            <span class="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[8px] font-bold text-slate-400 dark:text-slate-500 uppercase">${p.authType}</span>
                                            <span class="text-[9px] text-slate-400 dark:text-slate-500 font-medium">#${index + 1}</span>
                                        </div>
                                    </div>
                                </div>

                                <!-- Actions -->
                                <div class="flex items-center gap-3">
                                    <button onclick="testSingleConnectionRow('${p.id}', '${c.id}')" class="text-xs font-bold text-slate-500 hover:text-orange-500 flex items-center gap-1 cursor-pointer border-0 bg-transparent px-1.5 py-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors" title="Test kết nối này">
                                        <span class="material-symbols-outlined text-[16px]">bolt</span> <span class="hidden sm:inline">Test</span>
                                    </button>
                                    <button onclick="openEditConnectionModal('${c.id}')" class="text-xs font-bold text-slate-450 dark:text-slate-555 hover:text-orange-500 flex items-center gap-1 cursor-pointer border-0 bg-transparent">
                                        <span class="material-symbols-outlined text-[18px]">edit</span> <span class="hidden sm:inline">Edit</span>
                                    </button>
                                    <button onclick="deleteConnection('${p.id}', '${c.id}')" class="text-xs font-bold text-rose-500 hover:text-rose-700 flex items-center gap-1 cursor-pointer border-0 bg-transparent">
                                        <span class="material-symbols-outlined text-[18px] text-rose-500">delete</span> <span class="hidden sm:inline">Delete</span>
                                    </button>
                                    <label class="relative inline-flex items-center cursor-pointer">
                                        <input type="checkbox" ${c.enabled ? 'checked' : ''} onchange="toggleConnectionEnabled('${p.id}', '${c.id}', this.checked)" class="sr-only peer">
                                        <div class="w-7 h-4 bg-slate-200 dark:bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-350 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-orange-500"></div>
                                    </label>
                                </div>
                            </div>
                            <div id="quota-container-${c.id}" class="w-full pl-12 pr-4"></div>
                        `;
                        rowsContainer.appendChild(row);
                    });
                }
            }
            
            
            // Load and render models
            loadAndRenderModels(p.id);

            // Render provider-wide quota tracker on the right sidebar (bypassed)
            // renderProviderQuotaTracker(p.id);

            // Fetch and render connection quotas if provider is antigravity (bypassed)
            /*
            if (p.id === 'antigravity') {
                connections.forEach(c => {
                    loadAndRenderConnectionQuota(c.id);
                });
            }
            */
        } catch (err) {
            showErrorBanner('renderProviderDetails Error: ' + err.message + '\n' + err.stack);
        }
    }

    function renderProviderQuotaTracker(providerId) {
        const quotaContainer = document.getElementById('quota-tracker-container');
        if (!quotaContainer) return;

        const p = PROVIDERS_CATALOG[providerId];
        const data = localConfig.providers[providerId] || { connections: [] };
        const connections = (data.connections || []).filter(c => c.enabled);

        if (connections.length === 0) {
            quotaContainer.innerHTML = `
                <div class="text-[10px] text-slate-400 dark:text-slate-500 py-2">
                    No active connections to track quota.
                </div>
            `;
            return;
        }

        quotaContainer.innerHTML = '';
        connections.forEach(c => {
            const wrapper = document.createElement('div');
            wrapper.id = `quota-sidebar-conn-${c.id}`;
            wrapper.className = 'mb-4 last:mb-0 border border-slate-100 dark:border-slate-800 rounded-xl p-3 bg-white dark:bg-slate-900/50';
            quotaContainer.appendChild(wrapper);

            loadQuotaIntoContainer(c.id, c.name || c.id, wrapper.id);
        });
    }

    let modalMode = 'single';

    window.setModalMode = function(mode) {
        modalMode = mode;
        const singleFields = document.getElementById('modal-single-fields');
        const bulkFields = document.getElementById('modal-bulk-fields');
        const btnSingle = document.getElementById('btn-mode-single');
        const btnBulk = document.getElementById('btn-mode-bulk');
        const testBtn = document.getElementById('btn-modal-test');

        if (mode === 'single') {
            if (singleFields) { singleFields.classList.remove('hidden'); singleFields.style.display = 'block'; }
            if (bulkFields) { bulkFields.classList.add('hidden'); bulkFields.style.display = 'none'; }

            if (btnSingle) btnSingle.className = "flex-1 py-1.5 text-xs font-bold rounded-lg transition-all cursor-pointer bg-white dark:bg-slate-800 shadow-sm text-slate-800 dark:text-slate-100 border-0";
            if (btnBulk) btnBulk.className = "flex-1 py-1.5 text-xs font-bold rounded-lg transition-all cursor-pointer text-slate-500 dark:text-slate-455 hover:text-slate-800 dark:hover:text-slate-200 border-0 bg-transparent";
            
            if (testBtn) testBtn.style.display = 'flex';
        } else {
            if (singleFields) { singleFields.classList.add('hidden'); singleFields.style.display = 'none'; }
            if (bulkFields) { bulkFields.classList.remove('hidden'); bulkFields.style.display = 'block'; }

            if (btnSingle) btnSingle.className = "flex-1 py-1.5 text-xs font-bold rounded-lg transition-all cursor-pointer text-slate-500 dark:text-slate-455 hover:text-slate-800 dark:hover:text-slate-200 border-0 bg-transparent";
            if (btnBulk) btnBulk.className = "flex-1 py-1.5 text-xs font-bold rounded-lg transition-all cursor-pointer bg-white dark:bg-slate-800 shadow-sm text-slate-800 dark:text-slate-100 border-0";
            
            if (testBtn) testBtn.style.display = 'none';
        }
    };

    window.openAddConnectionModal = function() {
        editingConnectionId = null;
        const p = PROVIDERS_CATALOG[activeProviderId];
        if (!p) return;

        document.getElementById('modal-provider-icon').src = `/static/Images/providers/${p.logo}`;
        document.getElementById('modal-provider-title').textContent = `Thêm kết nối ${p.name}`;
        document.getElementById('modal-provider-subtitle').textContent = p.desc;
        
        const keyLabel = p.authType === 'OAuth' ? 'API Key / Access Token / Session Cookie' : 'API Key / Token (Khóa API)';
        document.getElementById('modal-key-label').textContent = keyLabel;
        
        const tabs = document.getElementById('modal-mode-tabs');
        document.getElementById('modal-conn-name-field')?.classList.remove('hidden');
        document.getElementById('modal-conn-url-field')?.classList.remove('hidden');
        document.getElementById('modal-conn-priority-field')?.classList.remove('hidden');
        if (tabs) tabs.style.display = 'flex';
        document.getElementById('modal-key-label')?.classList.remove('hidden');

        document.getElementById('modal-conn-key').placeholder = p.id === 'antigravity' ? 'AIzaSy... hoặc Google Access Token' : 'sk-... hoặc API Key';

        const signupUrl = p.signup || 'https://google.com';
        const hintEl = document.getElementById('modal-key-hint');
        if (hintEl) {
            if (p.id === 'antigravity') {
                hintEl.innerHTML = `
                    <div class="p-3 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl space-y-2 mt-2">
                        <span class="text-xs font-bold text-slate-700 dark:text-slate-300 block">🔑 Hướng dẫn lấy API Key Google:</span>
                        <div class="flex flex-wrap gap-2 pt-0.5">
                            <a href="${signupUrl}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white font-bold rounded-lg text-xs flex items-center gap-1 shadow-xs transition-all no-underline whitespace-nowrap">
                                🔗 Lấy Key Google AI Studio
                            </a>
                            <button type="button" onclick="startAntigravityOAuth()" class="px-3 py-1.5 bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-bold rounded-lg text-xs flex items-center gap-1 transition-all whitespace-nowrap">
                                🌐 Đăng nhập Google
                            </button>
                        </div>
                    </div>`;
                hintEl.classList.remove('hidden');
            } else {
                hintEl.innerHTML = `
                    <div class="p-3 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl space-y-2 mt-2">
                        <span class="text-xs font-bold text-slate-700 dark:text-slate-300 block">🔑 Hướng dẫn lấy Key ${p.name}:</span>
                        <div class="pt-0.5">
                            <a href="${signupUrl}" target="_blank" rel="noopener noreferrer" class="inline-flex px-3 py-1.5 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white font-bold rounded-lg text-xs items-center gap-1 shadow-xs transition-all no-underline whitespace-nowrap">
                                🔗 Lấy API Key ${p.name}
                            </a>
                        </div>
                    </div>`;
                hintEl.classList.remove('hidden');
            }
        }

        const existCount = ((localConfig.providers && localConfig.providers[p.id] && localConfig.providers[p.id].connections) || []).length + 1;
        document.getElementById('modal-conn-name').value = `${p.name} #${existCount}`;
        document.getElementById('modal-conn-key').value = '';
        document.getElementById('modal-conn-priority').value = '1';
        document.getElementById('modal-bulk-text').value = '';

        let defaultUrl = 'https://generativelanguage.googleapis.com';
        if (p.id === 'gemini' || p.id === 'antigravity') defaultUrl = 'https://generativelanguage.googleapis.com';
        else if (p.id === 'openai' || p.id === 'codex') defaultUrl = 'https://api.openai.com/v1';
        else if (p.id === 'deepseek') defaultUrl = 'https://api.deepseek.com';
        else if (p.id === 'groq') defaultUrl = 'https://api.groq.com/openai/v1';
        else if (p.id === 'openrouter') defaultUrl = 'https://openrouter.ai/api/v1';
        else if (p.id === 'nvidia') defaultUrl = 'https://integrate.api.nvidia.com/v1';
        else if (p.id === 'opencode') defaultUrl = 'https://opencode.ai/zen/v1';

        document.getElementById('modal-conn-url').value = defaultUrl;

        showCredentialModal();
    };

    window.openEditConnectionModal = function(connId) {
        editingConnectionId = connId;
        const p = PROVIDERS_CATALOG[activeProviderId];
        const data = localConfig.providers[p.id] || { connections: [] };
        const conn = data.connections.find(c => c.id === connId);
        if (!conn) return;

        document.getElementById('modal-provider-icon').src = `/static/Images/providers/${p.logo}`;
        document.getElementById('modal-provider-title').textContent = `Sửa kết nối ${p.name}`;
        document.getElementById('modal-provider-subtitle').textContent = p.desc;
        
        const keyLabel = p.authType === 'OAuth' ? 'API Key / Access Token / Session Cookie' : 'API Key / Token (Khóa API)';
        document.getElementById('modal-key-label').textContent = keyLabel;
        
        const signupUrl = p.signup || 'https://google.com';
        const hintEl = document.getElementById('modal-key-hint');
        if (hintEl) {
            hintEl.innerHTML = `
                <div class="p-3 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl space-y-2 mt-2">
                    <span class="text-xs font-bold text-slate-700 dark:text-slate-300 block">🔑 Hướng dẫn lấy Key ${p.name}:</span>
                    <div class="pt-0.5">
                        <a href="${signupUrl}" target="_blank" rel="noopener noreferrer" class="inline-flex px-3 py-1.5 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 text-white font-bold rounded-lg text-xs items-center gap-1 shadow-xs transition-all no-underline whitespace-nowrap">
                            🔗 Lấy API Key ${p.name}
                        </a>
                    </div>
                </div>`;
            hintEl.classList.remove('hidden');
        }
        
        document.getElementById('modal-conn-name').value = conn.name || '';
        document.getElementById('modal-conn-key').value = conn.api_key || '';
        document.getElementById('modal-conn-url').value = conn.base_url || '';
        document.getElementById('modal-conn-priority').value = conn.priority || '1';

        // Hide tabs for editing existing connection
        const tabs = document.getElementById('modal-mode-tabs');
        if (tabs) tabs.style.display = 'none';

        setModalMode('single');

        showCredentialModal();
    };

    function showCredentialModal() {
        const modal = document.getElementById('credential-modal');
        const content = document.getElementById('credential-modal-content');
        const statusEl = document.getElementById('modal-test-status');
        statusEl.textContent = '';

        modal.classList.remove('hidden');
        modal.style.display = 'flex';
        setTimeout(() => {
            content.classList.remove('scale-95', 'opacity-0');
            content.classList.add('scale-100', 'opacity-100');
        }, 50);
    }

    window.closeCredentialModal = function() {
        const modal = document.getElementById('credential-modal');
        const content = document.getElementById('credential-modal-content');

        content.classList.remove('scale-100', 'opacity-100');
        content.classList.add('scale-95', 'opacity-0');
        setTimeout(() => {
            modal.classList.add('hidden');
            modal.style.display = 'none';
        }, 150);
    };

    window.copyOAuthAuthUrl = function() {
        const input = document.getElementById('modal-oauth-authurl');
        if (input && input.value) {
            navigator.clipboard.writeText(input.value);
            toast('Đã sao chép URL xác thực!', 'success');
        }
    };

    window.startAntigravityOAuth = function() {
        const port = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
        const redirectUri = encodeURIComponent(`http://localhost:${port}/callback`);
        const state = Date.now() + '_' + Math.random().toString(36).substring(2, 8);
        const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com&response_type=code&redirect_uri=${redirectUri}&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcloud-platform+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.profile+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcclog+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fexperimentsandconfigs&access_type=offline&prompt=consent&state=${state}`;

        window.open(authUrl, "antigravity_oauth", "width=600,height=720,menubar=no,toolbar=no,location=no,status=no");
    };

    // Auto-receive OAuth callback data from popup window (9router style)
    async function _handleOAuthCallbackData(data) {
        if (!data || (!data.code && !data.fullUrl)) return;
        const codeOrUrl = data.fullUrl || data.code;

        const modal = document.getElementById('credential-modal');
        if (modal && !modal.classList.contains('hidden')) {
            const keyInput = document.getElementById('modal-conn-key');
            if (keyInput) {
                keyInput.value = codeOrUrl;
                const statusEl = document.getElementById('modal-test-status');
                if (statusEl) {
                    statusEl.textContent = '⚡ Đã nhận mã OAuth! Đang tự động kiểm tra & lưu kết nối...';
                    statusEl.className = 'text-[11px] font-semibold mt-2 min-h-[16px] text-amber-500 font-bold';
                }
                setTimeout(async () => {
                    await testConnection();
                    const statusText = (document.getElementById('modal-test-status')?.textContent || '');
                    if (statusText.includes('Thành công')) {
                        await saveConnection();
                        toast('✅ Đã tự động kết nối tài khoản Google Antigravity thành công!', 'success');
                    }
                }, 400);
            }
        }
    }

    window.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'oauth_callback') {
            _handleOAuthCallbackData(event.data.data);
        }
    });

    try {
        const bc = new BroadcastChannel('oauth_callback');
        bc.onmessage = (event) => {
            _handleOAuthCallbackData(event.data);
        };
    } catch(e) {}

    window.testConnection = async function() {
        const key = document.getElementById('modal-conn-key').value.trim();
        const url = document.getElementById('modal-conn-url').value.trim();
        const statusEl = document.getElementById('modal-test-status');
        const btn = document.getElementById('btn-modal-test');

        if (!key) {
            statusEl.textContent = '❌ API Key / Access Token không được để trống';
            statusEl.className = 'text-[11px] font-semibold mt-2 min-h-[16px] text-rose-600';
            return;
        }

        statusEl.textContent = '⏳ Đang kiểm tra kết nối...';
        statusEl.className = 'text-[11px] font-semibold mt-2 min-h-[16px] text-slate-500 dark:text-slate-400';
        btn.disabled = true;

        try {
            const res = await fetch('/api/test_api_key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: activeProviderId, key: key, base_url: url })
            });
            const data = await res.json();
            btn.disabled = false;

            if (data.ok) {
                statusEl.textContent = `✅ Thành công! (${data.quota || 'OK'})`;
                statusEl.className = 'text-[11px] font-semibold mt-2 min-h-[16px] text-emerald-600';
            } else {
                statusEl.textContent = `❌ Thất bại: ${data.error || 'Lỗi không xác định'}`;
                statusEl.className = 'text-[11px] font-semibold mt-2 min-h-[16px] text-rose-600';
            }
        } catch (e) {
            btn.disabled = false;
            statusEl.textContent = '❌ Lỗi hệ thống khi gửi yêu cầu.';
            statusEl.className = 'text-[11px] font-semibold mt-2 min-h-[16px] text-rose-600';
        }
    };

    // Auto-detect pasted callback URL or key and auto-test
    const keyInput = document.getElementById('modal-conn-key');
    if (keyInput) {
        keyInput.addEventListener('input', function() {
            const val = this.value.trim();
            if ((val.includes('code=') || val.startsWith('http') || val.length > 25) && !window._autoTesting) {
                window._autoTesting = true;
                setTimeout(async () => {
                    window._autoTesting = false;
                    await testConnection();
                }, 350);
            }
        });
    }

    window.saveConnection = async function() {
        const btn = document.getElementById('btn-modal-save');
        if (!activeProviderId) return;

        if (!localConfig.providers) localConfig.providers = {};
        if (!localConfig.providers[activeProviderId]) {
            localConfig.providers[activeProviderId] = { connections: [], strategy: 'fallback' };
        }
        const pData = localConfig.providers[activeProviderId];
        if (!pData.connections) pData.connections = [];

        if (modalMode === 'bulk') {
            const bulkText = document.getElementById('modal-bulk-text').value.trim();
            if (!bulkText) {
                toast('Vui lòng nhập danh sách API key', 'error');
                return;
            }

            const lines = bulkText.split('\n').map(l => l.trim()).filter(Boolean);
            if (lines.length === 0) return;

            btn.disabled = true;
            try {
                let addedCount = 0;
                lines.forEach((line, index) => {
                    const parts = line.split('|');
                    const key = parts.length >= 2 ? parts.slice(1).join('|').trim() : parts[0].trim();
                    const baseName = parts.length >= 2 ? parts[0].trim() : 'Connection';
                    const name = parts.length >= 2 ? baseName : `${baseName} #${index + 1}`;
                    
                    const newId = 'conn_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
                    pData.connections.push({
                        id: newId,
                        name: name,
                        api_key: key,
                        base_url: document.getElementById('modal-conn-url').value.trim(),
                        enabled: true,
                        priority: 1,
                        status: 'active'
                    });
                    addedCount++;
                });

                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ providers: localConfig.providers })
                });

                if (res.ok) {
                    toast(`Đã thêm thành công ${addedCount} kết nối`, 'success');
                    closeCredentialModal();
                    loadProvidersConfig();
                } else {
                    toast('Lỗi khi lưu cấu hình', 'error');
                }
            } catch (e) {
                toast('Lỗi hệ thống khi lưu bulk', 'error');
            } finally {
                btn.disabled = false;
            }

        } else {
            const name = document.getElementById('modal-conn-name').value.trim();
            const key = document.getElementById('modal-conn-key').value.trim();
            const url = document.getElementById('modal-conn-url').value.trim();
            const priority = parseInt(document.getElementById('modal-conn-priority').value.trim()) || 1;

            if (!name) {
                toast('Tên kết nối không được để trống', 'error');
                return;
            }

            btn.disabled = true;
            try {
                if (editingConnectionId) {
                    const conn = pData.connections.find(c => c.id === editingConnectionId);
                    if (conn) {
                        conn.name = name;
                        conn.api_key = key;
                        conn.base_url = url;
                        conn.priority = priority;
                    }
                } else {
                    const newId = 'conn_' + Date.now();
                    pData.connections.push({
                        id: newId,
                        name: name,
                        api_key: key,
                        base_url: url,
                        enabled: true,
                        priority: priority,
                        status: 'active'
                    });
                }

                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ providers: localConfig.providers })
                });

                if (res.ok) {
                    toast('Đã lưu kết nối thành công', 'success');
                    closeCredentialModal();
                    loadProvidersConfig();
                    // Tự động test ngay kết nối mới vừa lưu
                    const createdId = editingConnectionId || newId;
                    if (createdId) {
                        setTimeout(() => {
                            testSingleConnectionRow(activeProviderId, createdId);
                        }, 200);
                    }
                } else {
                    toast('Lỗi khi lưu kết nối', 'error');
                }
            } catch (e) {
                toast('Lỗi hệ thống khi lưu', 'error');
            } finally {
                btn.disabled = false;
            }
        }
    };

    window.toggleConnectionEnabled = async function(providerId, connId, checked) {
        try {
            const pData = localConfig.providers[providerId];
            if (!pData || !pData.connections) return;

            const conn = pData.connections.find(c => c.id === connId);
            if (conn) {
                conn.enabled = !!checked;
                if (!checked) {
                    conn.status = 'disabled';
                }
            }

            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ providers: localConfig.providers })
            });

            if (res.ok) {
                toast(`Đã ${checked ? 'bật' : 'tắt'} kết nối`, 'success');
                loadProvidersConfig();
                if (checked) {
                    // Khi vừa bật kết nối -> tự động test ngay kết nối đó
                    setTimeout(() => {
                        testSingleConnectionRow(providerId, connId);
                    }, 150);
                }
            } else {
                toast('Lỗi khi cập nhật trạng thái', 'error');
            }
        } catch (e) {
            toast('Lỗi hệ thống khi cập nhật', 'error');
        }
    };

    window.toggleAllConnections = async function(providerId, checked) {
        try {
            const pData = localConfig.providers[providerId];
            if (!pData || !pData.connections) return;

            pData.connections.forEach(c => {
                c.enabled = !!checked;
                if (!checked) {
                    c.status = 'disabled';
                }
            });

            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ providers: localConfig.providers })
            });

            if (res.ok) {
                toast(`Đã ${checked ? 'bật' : 'tắt'} tất cả kết nối`, 'success');
                loadProvidersConfig();
            }
        } catch (e) {
            toast('Lỗi hệ thống', 'error');
        }
    };

    window.deleteConnection = async function(providerId, connId) {
        if (!confirm('Bạn có chắc chắn muốn xóa kết nối này?')) return;
        try {
            const pData = localConfig.providers[providerId];
            if (!pData || !pData.connections) return;

            pData.connections = pData.connections.filter(c => c.id !== connId);

            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ providers: localConfig.providers })
            });

            if (res.ok) {
                toast('Đã xóa kết nối thành công', 'success');
                loadProvidersConfig();
            }
        } catch (e) {
            toast('Lỗi hệ thống', 'error');
        }
    };

    window.moveConnection = async function(providerId, connId, direction) {
        try {
            const pData = localConfig.providers[providerId];
            if (!pData || !pData.connections) return;

            const index = pData.connections.findIndex(c => c.id === connId);
            if (index === -1) return;

            const targetIndex = index + direction;
            if (targetIndex < 0 || targetIndex >= pData.connections.length) return;

            // Swap connections
            const temp = pData.connections[index];
            pData.connections[index] = pData.connections[targetIndex];
            pData.connections[targetIndex] = temp;

            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ providers: localConfig.providers })
            });

            if (res.ok) {
                loadProvidersConfig();
            }
        } catch (e) {
            // ignore
        }
    };

    window.testSingleConnectionRow = async function(providerId, connId) {
        const pData = localConfig.providers[providerId];
        if (!pData || !pData.connections) return;
        const conn = pData.connections.find(c => c.id === connId);
        if (!conn) return;

        conn.status = 'testing';
        renderProviderDetails();

        try {
            const res = await fetch('/api/test_api_key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: providerId, key: conn.api_key, base_url: conn.base_url })
            });
            const data = await res.json();
            conn.status = data.ok ? 'active' : 'error';
            if (data.ok) {
                toast(`Kết nối "${conn.name || conn.id}" hoạt động tốt!`, 'success');
            } else {
                toast(`Kết nối "${conn.name || conn.id}" thất bại: ${data.error || 'Mã/Key không hợp lệ'}`, 'error');
            }
        } catch (e) {
            conn.status = 'error';
            toast(`Lỗi hệ thống khi kiểm tra kết nối "${conn.name || conn.id}"`, 'error');
        }

        // Save status back to DB
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ providers: localConfig.providers })
        });

        renderProviderDetails();
    };

    window.testConnectionsOneByOne = async function(silent = false) {
        if (!activeProviderId || !PROVIDERS_CATALOG[activeProviderId]) return;
        const p = PROVIDERS_CATALOG[activeProviderId];
        const pData = (localConfig.providers && localConfig.providers[p.id]) || { connections: [] };
        if (!pData || !pData.connections || pData.connections.length === 0) return;

        const enabledConnections = pData.connections.filter(c => c.enabled);
        if (enabledConnections.length === 0) {
            if (!silent) toast('Không có kết nối nào đang bật (enabled) để kiểm tra!', 'warning');
            return;
        }

        if (!silent) toast('Đang chạy kiểm tra tuần tự...', 'info');
        const btn = document.getElementById('btn-test-one-by-one');
        if (btn) btn.disabled = true;

        for (const c of pData.connections) {
            if (!c.enabled) continue;
            c.status = 'testing';
            renderProviderDetails();

            try {
                const res = await fetch('/api/test_api_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: p.id, key: c.api_key, base_url: c.base_url })
                });
                const data = await res.json();
                c.status = data.ok ? 'active' : 'error';
            } catch (e) {
                c.status = 'error';
            }
            renderProviderDetails();
            await new Promise(r => setTimeout(r, 300));
        }

        // Save status back to DB
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ providers: localConfig.providers })
        });

        if (btn) btn.disabled = false;
        if (!silent) toast('Đã kiểm tra xong các kết nối!', 'success');
    };

    window.testBatchProviders = async function(category) {
        toast('Đang chạy test hàng loạt...', 'info');
        const pIds = Object.values(PROVIDERS_CATALOG)
            .filter(p => p.category === category)
            .map(p => p.id);

        for (const id of pIds) {
            const pData = localConfig.providers[id];
            if (!pData || !pData.connections) continue;
            
            for (const c of pData.connections) {
                if (!c.enabled) continue;
                try {
                    const res = await fetch('/api/test_api_key', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ provider: id, key: c.api_key, base_url: c.base_url })
                    });
                    const data = await res.json();
                    c.status = data.ok ? 'active' : 'error';
                } catch (e) {
                    c.status = 'error';
                }
            }
        }

        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ providers: localConfig.providers })
        });

        loadProvidersConfig();
        toast('Test h�ng lo?t ho�n t?t!', 'success');
    };

    window.openCustomCompatibleModal = function(type) {
        editingConnectionId = null;
        activeProviderId = type === 'openai' ? 'custom_openai' : 'custom_anthropic';
        
        // Ensure catalog entry exists for dynamic custom providers
        if (!PROVIDERS_CATALOG[activeProviderId]) {
            PROVIDERS_CATALOG[activeProviderId] = {
                id: activeProviderId,
                name: type === 'openai' ? 'OpenAI Compatible' : 'Anthropic Compatible',
                category: 'oauth',
                logo: type === 'openai' ? 'oai-cc.png' : 'anthropic-m.png',
                color: type === 'openai' ? '#10A37F' : '#D97757',
                textIcon: type === 'openai' ? 'OC' : 'AC',
                desc: type === 'openai' ? 'Custom OpenAI Compatible API' : 'Custom Anthropic Compatible API',
                authType: 'API Key',
                signup: '#'
            };
        }

        document.getElementById('modal-provider-icon').src = `/static/Images/providers/${PROVIDERS_CATALOG[activeProviderId].logo}`;
        document.getElementById('modal-provider-title').textContent = `Add Custom ${type === 'openai' ? 'OpenAI' : 'Anthropic'} Compatible`;
        document.getElementById('modal-provider-subtitle').textContent = `Cấu hình endpoint tùy chỉnh tương thích ${type === 'openai' ? 'OpenAI' : 'Anthropic'}`;
        document.getElementById('modal-key-label').textContent = 'API Key / Bearer Token';
        
        document.getElementById('modal-conn-name').value = '';
        document.getElementById('modal-conn-key').value = '';
        document.getElementById('modal-conn-url').value = type === 'openai' ? 'https://api.openai.com/v1' : 'https://api.anthropic.com/v1';

        showCredentialModal();
    };

    window.disableAllModels = async function() {
        if (!activeProviderId) return;
        if (!confirm('B?n c� ch?c ch?n mu?n t?t t?t c? model cho provider n�y?')) return;
        try {
            log(`disableAllModels for ${activeProviderId}`);
            const res = await fetch('/api/providers/models/disable_all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: activeProviderId })
            });
            if (res.ok) {
                toast('?� t?t t?t c? models', 'success');
                loadAndRenderModels(activeProviderId);
            } else {
                toast('L?i khi th?c hi?n', 'error');
            }
        } catch (e) {
            toast('L?i h? th?ng', 'error');
        }
    };

    async function loadAndRenderModels(providerId) {
        try {
            log('loadAndRenderModels initiated for ' + providerId);
            const res = await fetch(`/api/providers/models?provider=${providerId}`);
            if (!res.ok) {
                log('fetch models failed status: ' + res.status);
                return;
            }
            const data = await res.json();
            if (!data.ok) {
                log('API error fetching models: ' + data.error);
                return;
            }

            // Set thinking mode select
            const selectThinking = document.getElementById('select-thinking-mode');
            if (selectThinking) {
                selectThinking.value = data.thinking_mode || 'auto';
            }

            const modelsContainer = document.getElementById('models-list-container');
            if (!modelsContainer) return;

            modelsContainer.innerHTML = '';

            const models = data.models || [];
            const activeModels = models.filter(m => m.enabled);
            const disabledModels = models.filter(m => !m.enabled);

            // Toggle Active All button visibility
            const btnActiveAll = document.getElementById('btn-active-all');
            if (btnActiveAll) {
                if (disabledModels.length > 0) {
                    btnActiveAll.classList.remove('hidden');
                } else {
                    btnActiveAll.classList.add('hidden');
                }
                 const activeConnections = (localConfig.providers[providerId]?.connections || []).filter(c => c.enabled);
                const hasActiveConnections = activeConnections.length > 0;

                activeModels.forEach(m => {
                    let visionIcon = '';
                    let thinkingIcon = '';
                    const mid = m.id.toLowerCase();

                    if (mid.includes('gemini') || mid.includes('claude') || mid.includes('vision') || mid.includes('gpt-4o')) {
                        visionIcon = '👀';
                    }
                    if (mid.includes('agent') || mid.includes('thinking') || mid.includes('reasoner') || mid.includes('low') || mid.includes('medium') || mid.includes('high') || mid.includes('oss')) {
                        thinkingIcon = '🧠';
                    }

                    // Determine icon based on test status
                    const testStatus = modelTestStatuses[m.id] || 'idle';
                    let statusIcon = '<span class="material-symbols-outlined text-slate-455 dark:text-slate-555 text-lg shrink-0">smart_toy</span>';
                    if (testStatus === 'testing') {
                        statusIcon = '<span class="w-4 h-4 border-2 border-slate-350 dark:border-slate-700 border-t-transparent dark:border-t-transparent rounded-full animate-spin shrink-0"></span>';
                    } else if (testStatus === 'ok') {
                        statusIcon = '<span class="material-symbols-outlined text-emerald-500 text-lg shrink-0" title="Test OK">check_circle</span>';
                    } else if (testStatus === 'error') {
                        statusIcon = '<span class="material-symbols-outlined text-rose-500 text-lg shrink-0" title="Test Failed">cancel</span>';
                    }

                    let testBtnHtml = '';
                    const provObj = PROVIDERS_CATALOG[providerId];
                    if (hasActiveConnections || (provObj && provObj.noAuth)) {
                        testBtnHtml = `
                            <button onclick="testModel('${providerId}', '${m.id}')" class="rounded p-0.5 text-slate-400 opacity-100 transition-opacity hover:bg-slate-100 dark:hover:bg-slate-850 hover:text-orange-500 sm:opacity-0 sm:group-hover:opacity-100 cursor-pointer border-none bg-transparent" title="Test this model">
                                <span class="material-symbols-outlined text-sm">science</span>
                            </button>
                        `;
                    }

                    function getProviderModelPrefix(pId) {
                        const aliases = {
                            opencode: 'oc',
                            antigravity: 'ag',
                            gemini: 'gc',
                            qoder: 'qd',
                            kiro: 'kr',
                            'xiaomi-mimo': 'mimo'
                        };
                        return aliases[pId] || pId;
                    }

                    const item = document.createElement('div');
                    item.className = 'group min-w-0 max-w-full rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-2 bg-slate-50/50 dark:bg-slate-900/30 hover:bg-slate-100/50 dark:hover:bg-slate-800/50 transition-all';
                    item.innerHTML = `
                        <div class="flex min-w-0 items-center gap-2">
                            ${statusIcon}
                            <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                                <code class="truncate rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 font-mono text-xs text-slate-600 dark:text-slate-400 max-w-[180px] block">${getProviderModelPrefix(providerId)}/${m.id}</code>
                                <span class="truncate pl-1 text-[9px] italic text-slate-400 dark:text-slate-500 block" title="${m.name || m.id}">
                                    ${m.name || m.id} ${visionIcon} ${thinkingIcon}
                                </span>
                            </div>
                            ${testBtnHtml}
                            <button onclick="copyToClipboard('${providerId}/${m.id}')" class="rounded p-0.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-orange-500 cursor-pointer border-none bg-transparent" title="Copy model name">
                                <span class="material-symbols-outlined text-sm">content_copy</span>
                            </button>
                            <button onclick="toggleModelEnabled('${providerId}', '${m.id}', false)" class="ml-auto rounded p-0.5 text-slate-400 opacity-100 transition-opacity hover:bg-red-500/10 hover:text-red-500 sm:opacity-0 sm:group-hover:opacity-100 cursor-pointer border-none bg-transparent" title="Disable this model">
                                <span class="material-symbols-outlined text-sm">close</span>
                            </button>
                        </div>
                    `;
                    modelsContainer.appendChild(item);
                });
            }

            // Disabled models section
            let disabledSection = document.getElementById('disabled-models-container');
            if (!disabledSection) {
                disabledSection = document.createElement('div');
                disabledSection.id = 'disabled-models-container';
                disabledSection.className = 'w-full mt-4 border-t border-dashed border-slate-200 dark:border-slate-800 pt-3';
                modelsContainer.parentNode.appendChild(disabledSection);
            }

            if (disabledModels.length > 0) {
                disabledSection.innerHTML = `
                    <p class="text-[10px] font-bold text-slate-450 dark:text-slate-550 mb-2">Disabled models (${disabledModels.length}):</p>
                    <div class="flex flex-wrap gap-2">
                        ${disabledModels.map(m => `
                            <button onclick="toggleModelEnabled('${providerId}', '${m.id}', true)" class="px-2 py-1 rounded-lg border border-dashed border-slate-200 dark:border-slate-800 hover:border-orange-500/50 text-[10px] text-slate-450 hover:text-orange-500 dark:text-slate-500 transition-all cursor-pointer bg-transparent" title="Click to enable model">
                                ? ${m.id}
                            </button>
                        `).join('')}
                    </div>
                `;
            } else {
                disabledSection.innerHTML = '';
            }

            log(`Rendered active/disabled models for ${providerId}`);
        } catch (e) {
            log('loadAndRenderModels Exception: ' + e.message);
        }
    }

    window.copyToClipboard = function(text) {
        navigator.clipboard.writeText(text).then(() => {
            toast('?� copy: ' + text, 'success');
        }).catch(err => {
            toast('L?i khi copy', 'error');
        });
    };

    window.activeAllModels = async function() {
        if (!activeProviderId) return;
        try {
            log('activeAllModels initiated for ' + activeProviderId);
            const res = await fetch('/api/providers/models/enable_all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: activeProviderId })
            });
            if (res.ok) {
                toast('?� k�ch ho?t l?i t?t c? models', 'success');
                loadAndRenderModels(activeProviderId);
            } else {
                toast('L?i khi th?c hi?n', 'error');
            }
        } catch (e) {
            toast('L?i h? th?ng', 'error');
        }
    };

    window.testModel = async function(providerId, modelId) {
        if (modelTestStatuses[modelId] === 'testing') return;

        modelTestStatuses[modelId] = 'testing';
        loadAndRenderModels(providerId);

        try {
            log(`Testing model: ${providerId}/${modelId}`);
            const res = await fetch('/api/models/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: `${providerId}/${modelId}` })
            });
            const data = await res.json();
            if (res.ok && data.ok) {
                modelTestStatuses[modelId] = 'ok';
                toast(`Model ${modelId} hoạt động tốt!`, 'success');
            } else {
                modelTestStatuses[modelId] = 'error';
                toast(`Lỗi khi test model ${modelId}: ${data.error || 'Lỗi kết nối'}`, 'error');
            }
        } catch (e) {
            modelTestStatuses[modelId] = 'error';
            toast(`Lỗi hệ thống khi test model: ${e.message}`, 'error');
        }
        loadAndRenderModels(providerId);
    };

    window.toggleModelEnabled = async function(providerId, modelId, checked) {
        try {
            log(`toggleModelEnabled: ${providerId} / ${modelId} -> ${checked}`);
            const res = await fetch('/api/providers/models/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: providerId, model_id: modelId, enabled: checked })
            });
            if (res.ok) {
                toast(`?� ${checked ? 'b?t' : 't?t'} model ${modelId}`, 'success');
                loadAndRenderModels(providerId);
            } else {
                toast('L?i khi c?p nh?t tr?ng th�i model', 'error');
            }
        } catch (e) {
            toast('L?i h? th?ng', 'error');
        }
    };

    // Bind Round Robin strategy change
    document.addEventListener('change', async (e) => {
        if (e.target && e.target.id === 'toggle-round-robin') {
            const checked = e.target.checked;
            if (!activeProviderId) return;

            const pData = localConfig.providers[activeProviderId];
            if (!pData) return;

            pData.strategy = checked ? 'round-robin' : 'fallback';

            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ providers: localConfig.providers })
            });

            if (res.ok) {
                toast(`?� thay ??i chi?n l??c ?i?u ph?i sang ${checked ? 'Round Robin' : 'Fallback'}`, 'success');
            }
        }

        if (e.target && e.target.id === 'select-thinking-mode') {
            const mode = e.target.value;
            if (!activeProviderId) return;
            try {
                log(`Setting thinking mode for ${activeProviderId} to ${mode}`);
                const res = await fetch('/api/providers/thinking_mode', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider: activeProviderId, mode: mode })
                });
                if (res.ok) {
                    toast(`?� l?u ch? ?? thinking: ${mode}`, 'success');
                } else {
                    toast('L?i khi c?u h�nh thinking mode', 'error');
                }
            } catch (e) {
                toast('L?i h? th?ng', 'error');
            }
        }
    });

    async function loadAndRenderConnectionQuota(connectionId) {
        const quotaContainer = document.getElementById(`quota-container-${connectionId}`);
        if (!quotaContainer) return;

        quotaContainer.innerHTML = `
            <div class="flex items-center gap-1.5 py-2 text-slate-400 dark:text-slate-500">
                <span class="w-3 h-3 border border-slate-350 dark:border-slate-700 border-t-transparent dark:border-t-transparent rounded-full animate-spin"></span>
                <span class="text-[10px]">Loading quota tracker...</span>
            </div>
        `;

        try {
            const res = await fetch(`/api/usage/${connectionId}`);
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                quotaContainer.innerHTML = `
                    <div class="text-[10px] text-rose-500 py-1 flex items-center gap-1">
                        <span class="material-symbols-outlined text-xs">warning</span> Quota unavailable: ${errData.error || res.statusText}
                    </div>
                `;
                return;
            }

            const data = await res.json();
            if (!data.ok) {
                quotaContainer.innerHTML = `
                    <div class="text-[10px] text-slate-450 dark:text-slate-500 py-1">
                        ${data.message || 'No quota info available.'}
                    </div>
                `;
                return;
            }

            const quotas = data.quotas || [];
            if (quotas.length === 0) {
                quotaContainer.innerHTML = `
                    <div class="text-[10px] text-slate-450 dark:text-slate-500 py-1">
                        No quota limits defined.
                    </div>
                `;
                return;
            }

            let html = `
                <div class="mt-2 border-t border-slate-100 dark:border-slate-850/60 pt-2 space-y-2">
                    <div class="flex items-center justify-between text-[10px] text-slate-450 dark:text-slate-500">
                        <span class="flex items-center gap-1"><span class="material-symbols-outlined text-xs text-orange-500">monitoring</span> Quota Tracker (Plan: <strong>${data.plan || 'Pro'}</strong>)</span>
                        <span>${quotas.length} models tracked</span>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            `;

            quotas.forEach(q => {
                const pct = q.remaining;
                let colorClass = 'bg-emerald-500';
                let textClass = 'text-emerald-600 dark:text-emerald-400';
                let emoji = '🟢';
                if (pct < 30) {
                    colorClass = 'bg-rose-500';
                    textClass = 'text-rose-600 dark:text-rose-450';
                    emoji = '🔴';
                } else if (pct < 70) {
                    colorClass = 'bg-amber-500';
                    textClass = 'text-amber-600 dark:text-amber-450';
                    emoji = '🟡';
                }

                let resetStr = 'N/A';
                if (q.resetAt) {
                    try {
                        const resetDate = new Date(q.resetAt);
                        const diffMs = resetDate.getTime() - Date.now();
                        if (diffMs > 0) {
                            const diffHrs = Math.floor(diffMs / 3600000);
                            const diffMins = Math.floor((diffMs % 3600000) / 60000);
                            resetStr = `in ${diffHrs}h ${diffMins}m`;
                        } else {
                            resetStr = 'Resetting...';
                        }
                    } catch (e) {
                        resetStr = 'N/A';
                    }
                }

                html += `
                    <div class="bg-slate-50/50 dark:bg-slate-900/30 border border-slate-100 dark:border-slate-805 rounded-xl p-2.5 space-y-1">
                        <div class="flex items-center justify-between text-[11px]">
                            <span class="font-bold text-slate-700 dark:text-slate-350 truncate max-w-[180px]">${emoji} ${q.name}</span>
                            <span class="text-[9px] text-slate-450 dark:text-slate-500 font-mono">${q.model_id}</span>
                        </div>
                        <div class="h-1.5 w-full bg-slate-200 dark:bg-slate-850 rounded-full overflow-hidden">
                            <div class="h-full ${colorClass} transition-all duration-300" style="width: ${pct}%"></div>
                        </div>
                        <div class="flex items-center justify-between text-[9px] text-slate-450 dark:text-slate-500">
                            <span>Used: <strong>${q.used}</strong> / ${q.total}</span>
                            <span class="font-bold ${textClass}">${pct}% left</span>
                            <span>Reset: <strong>${resetStr}</strong></span>
                        </div>
                    </div>
                `;
            });

            html += `
                    </div>
                </div>
            `;
            quotaContainer.innerHTML = html;

        } catch (err) {
            quotaContainer.innerHTML = `
                <div class="text-[10px] text-rose-500 py-1 flex items-center gap-1">
                    <span class="material-symbols-outlined text-xs">error</span> Error loading quota tracker: ${err.message}
                </div>
            `;
        }
    }

    window.toggleSystemSection = function() {
        const body = document.getElementById('system-section-body');
        const arrow = document.getElementById('system-section-arrow');
        if (body && arrow) {
            body.classList.toggle('hidden');
            arrow.style.transform = body.classList.contains('hidden') ? '' : 'rotate(180deg)';
        }
    };

    window.toggleSubSection = function(id) {
        const body = document.getElementById(id + '-body');
        const arrow = document.getElementById(id + '-arrow');
        if (body && arrow) {
            body.classList.toggle('hidden');
            arrow.style.transform = body.classList.contains('hidden') ? '' : 'rotate(180deg)';
        }
    };

    window.scrollToMediaProvider = function(kind) {
        toast(`Media Provider: ${kind} (ch?a tri?n khai)`, 'info');
    };

    window.refreshAllQuotas = async function() {
        if (activeProviderId) {
            renderProviderQuotaTracker(activeProviderId);
            return;
        }

        const container = document.getElementById('quota-page-tracker-container');
        if (!container) return;
        
        container.innerHTML = `
            <div class="text-center py-12 text-slate-450 dark:text-slate-550 space-y-2 col-span-full">
                <span class="w-6 h-6 border-2 border-slate-350 dark:border-slate-750 border-t-transparent dark:border-t-transparent rounded-full animate-spin inline-block"></span>
                <p class="text-xs">Đang quét hạn mức tất cả kết nối...</p>
            </div>
        `;

        try {
            const res = await fetch('/api/config');
            if (!res.ok) throw new Error('Không thể tải cấu hình');
            const data = await res.json();
            
            const providers = data.providers || {};
            let allConns = [];
            Object.keys(providers).forEach(provId => {
                const conns = providers[provId].connections || [];
                conns.forEach(c => {
                    c.provider = provId;
                    allConns.push(c);
                });
            });

            const activeConns = allConns.filter(c => c.enabled);
            
            if (activeConns.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-12 text-slate-400 col-span-full">
                        ⚠️ Không tìm thấy kết nối nào được kích hoạt. Hãy cấu hình ở mục AI Providers trước.
                    </div>
                `;
                return;
            }

            container.innerHTML = '';
            
            activeConns.forEach(c => {
                const div = document.createElement('div');
                div.id = `quota-page-main-${c.id}`;
                div.innerHTML = `<div class="text-[11px] text-slate-450 py-2">Đang tải hạn mức cho ${c.name || c.id}...</div>`;
                container.appendChild(div);
                loadQuotaIntoContainer(c.id, c.name || c.id, `quota-page-main-${c.id}`);
            });
        } catch (e) {
            container.innerHTML = `
                <div class="text-center py-12 text-rose-500 col-span-full">
                    ⚠️ Lỗi: ${e.message}
                </div>
            `;
        }
    };

    async function loadQuotaIntoContainer(connectionId, connName, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        try {
            const res = await fetch(`/api/usage/${connectionId}`);
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                container.innerHTML = `
                    <div class="p-3 text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/60 rounded-xl flex items-center gap-2">
                        <span class="material-symbols-outlined text-base shrink-0">warning</span>
                        <span><strong>${connName}</strong>: ${errData.error || res.statusText}</span>
                    </div>
                `;
                return;
            }

            const data = await res.json();
            if (!data.ok) {
                container.innerHTML = `
                    <div class="p-3 text-xs text-slate-400 bg-slate-50/50 dark:bg-slate-900/50 border border-slate-100 dark:border-slate-805 rounded-xl">
                        ${connName}: ${data.message || 'No quota details.'}
                    </div>
                `;
                return;
            }

            const quotas = data.quotas || [];
            const pInfo = PROVIDERS_CATALOG[data.provider] || { color: '#6B7280', logo: 'antigravity.png', name: data.provider };
            const providerColor = pInfo.color || '#6B7280';
            const providerLogo = pInfo.logo ? `/static/Images/providers/${pInfo.logo}` : '';

            // 9Router Card classes and header layout
            let html = `
                <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-850 rounded-2xl overflow-hidden shadow-xs flex flex-col">
                    <!-- Header -->
                    <div class="px-3 py-2 border-b border-slate-100 dark:border-slate-850/60 bg-slate-50/20 dark:bg-slate-900/20">
                        <div class="flex items-center justify-between gap-2">
                            <div class="flex items-center gap-2 min-w-0">
                                <div class="w-8 h-8 shrink-0 rounded-lg flex items-center justify-center overflow-hidden bg-slate-100/50 dark:bg-slate-800/50" style="background-color: ${providerColor}15">
                                    ${providerLogo ? `<img src="${providerLogo}" class="w-5 h-5 object-contain" onerror="this.outerHTML='<span class=\\'font-bold text-[10px]\\'>${data.provider?.slice(0, 2).toUpperCase()}</span>'">` : `<span class="font-bold text-[10px] text-slate-400">${data.provider?.slice(0, 2).toUpperCase()}</span>`}
                                </div>
                                <div class="min-w-0">
                                    <h3 class="text-xs font-semibold text-slate-800 dark:text-slate-200 capitalize truncate">${data.provider || 'Antigravity'}</h3>
                                    <p class="text-[10px] text-slate-400 dark:text-slate-500 truncate max-w-[180px]">${data.email || data.name || connName}</p>
                                </div>
                            </div>
                            
                        </div>
                    </div>

                    <!-- Card Body containing QuotaTable -->
                    <div class="p-3">
            `;

            if (quotas.length === 0) {
                html += `
                    <div class="text-center py-8 text-slate-400 dark:text-slate-500 flex flex-col items-center justify-center gap-2">
                        <span class="material-symbols-outlined text-[48px] opacity-20">data_usage</span>
                        <p class="text-sm mt-1">No quota data available</p>
                    </div>
                `;
            } else {
                html += `
                    <div class="space-y-2">
                        <div class="flex items-center justify-between gap-2 text-[10px] text-slate-400 dark:text-slate-500 mb-1">
                            <span>${quotas.length} quotas</span>
                        </div>
                        <div class="overflow-x-auto">
                            <table class="w-full table-fixed text-left">
                                <tbody>
                `;

                quotas.forEach(q => {
                    const pct = q.remaining;
                    let colorClass = 'bg-green-500';
                    let textClass = 'text-green-600 dark:text-green-400';
                    let bgLight = 'bg-green-500/10';
                    let emoji = '🟢';
                    
                    if (pct < 30) {
                        colorClass = 'bg-red-500';
                        textClass = 'text-red-600 dark:text-red-400';
                        bgLight = 'bg-red-500/10';
                        emoji = '🔴';
                    } else if (pct < 70) {
                        colorClass = 'bg-yellow-500';
                        textClass = 'text-yellow-600 dark:text-yellow-400';
                        bgLight = 'bg-yellow-500/10';
                        emoji = '🟡';
                    }

                    let resetStr = '✅';
                    if (q.resetAt) {
                        try {
                            const diffMs = new Date(q.resetAt).getTime() - Date.now();
                            if (diffMs > 0) {
                                const diffHrs = Math.floor(diffMs / 3600000);
                                const diffMins = Math.floor((diffMs % 3600000) / 60000);
                                resetStr = `⏳ ${diffHrs}h ${diffMins}m`;
                            } else {
                                resetStr = '🔄 Resetting...';
                            }
                        } catch(e) {}
                    }

                    html += `
                        <tr class="border-b border-slate-50 dark:border-slate-850 hover:bg-slate-50/40 dark:hover:bg-slate-850/40 transition-colors">
                            <!-- Model Name -->
                            <td class="py-1.5 px-2 w-[35%] align-middle">
                                <div class="flex items-center gap-1.5 min-w-0">
                                    <span class="text-[10px] shrink-0">${emoji}</span>
                                    <span class="text-[11px] font-medium text-slate-700 dark:text-slate-300 truncate" title="${q.name}">
                                        ${q.name}
                                    </span>
                                </div>
                            </td>

                            <!-- Progress Bar -->
                            <td class="py-1.5 px-2 w-[45%] align-middle">
                                <div class="space-y-1">
                                    <div class="h-1 rounded-full overflow-hidden bg-slate-100 dark:bg-slate-800 ${bgLight}">
                                        <div class="h-full ${colorClass} transition-all duration-300" style="width: ${pct}%"></div>
                                    </div>
                                    <div class="flex items-center justify-between text-[9px] text-slate-400">
                                        <span>${q.used.toLocaleString()} / ${q.total > 0 ? q.total.toLocaleString() : '?'}</span>
                                        <span class="font-bold ${textClass}">${pct}%</span>
                                    </div>
                                </div>
                            </td>

                            <!-- Reset Time -->
                            <td class="py-1.5 px-2 w-[20%] align-middle text-right">
                                <span class="text-[10px] text-slate-700 dark:text-slate-300 font-medium">
                                    ${resetStr}
                                </span>
                            </td>
                        </tr>
                    `;
                });

                html += `
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
            }

            html += `
                    </div>
                </div>
            `;
            container.innerHTML = html;

        } catch (err) {
            container.innerHTML = `
                <div class="p-3 text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/60 rounded-xl flex items-center gap-2">
                    <span class="material-symbols-outlined text-base shrink-0">error</span>
                    <span>Error loading quota card: ${err.message}</span>
                </div>
            `;
        }
    }

    // Run automatically if active
    const pageEl = document.getElementById('page-providers');
    if (pageEl && pageEl.classList.contains('active')) {
        loadProvidersConfig();
    }

})();

