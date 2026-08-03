(function() {
    const MEDIA_PROVIDERS = {
        tts: [
            { id: 'edge-tts', name: 'Edge TTS', desc: 'Free Microsoft Edge Speech voices', logo: 'edge-tts.png', textIcon: 'ET', color: '#0078D4', isBuiltIn: true },
            { id: 'google-tts', name: 'Google TTS', desc: 'Standard Android/Web Speech Synthesis', logo: 'google-tts.png', textIcon: 'GT', color: '#4285F4', isBuiltIn: true },
            { id: 'local-device', name: 'Local Device', desc: 'System native text-to-speech engine', logo: 'local-device.png', textIcon: 'LD', color: '#64748B', isBuiltIn: true },
            { id: 'openrouter', name: 'OpenRouter', desc: 'OpenRouter TTS endpoints', logo: 'openrouter.png', textIcon: 'OR', color: '#F97316' },
            { id: 'gemini', name: 'Gemini', desc: 'Gemini TTS models', logo: 'gemini.png', textIcon: 'GE', color: '#4285F4' },
            { id: 'openai', name: 'OpenAI', desc: 'OpenAI TTS (tts-1, tts-1-hd)', logo: 'openai.png', textIcon: 'OA', color: '#10A37F' },
            { id: 'nvidia', name: 'NVIDIA NIM', desc: 'FastPitch / Tacotron2 models', logo: 'nvidia.png', textIcon: 'NV', color: '#76B900' },
            { id: 'minimax', name: 'Minimax Coding', desc: 'Speech 2.8 HD/Turbo voice API', logo: 'minimax.png', textIcon: 'MM', color: '#7C3AED' },
            { id: 'minimax-cn', name: 'Minimax (China)', desc: 'Chinese regional Speech API', logo: 'minimax-cn.png', textIcon: 'MC', color: '#DC2626' },
            { id: 'hyperbolic', name: 'Hyperbolic', desc: 'Melo TTS voices', logo: 'hyperbolic.png', textIcon: 'HP', color: '#00D4FF' },
            { id: 'deepgram', name: 'Deepgram', desc: 'Aura speech synthesis', logo: 'deepgram.png', textIcon: 'DG', color: '#13EF93' },
            { id: 'elevenlabs', name: 'ElevenLabs', desc: 'Eleven Multilingual v2', logo: 'elevenlabs.png', textIcon: 'EL', color: '#6C47FF' },
            { id: 'cartesia', name: 'Cartesia', desc: 'Sonic voice generation', logo: 'cartesia.png', textIcon: 'CA', color: '#FF4F8B' },
            { id: 'playht', name: 'PlayHT', desc: 'PlayDialog voice models', logo: 'playht.png', textIcon: 'PH', color: '#00B4D8' },
            { id: 'coqui', name: 'Coqui TTS', desc: 'Local custom Tacotron2 server', logo: 'coqui.png', textIcon: 'CQ', color: '#10B981', isLocal: true },
            { id: 'tortoise', name: 'Tortoise TTS', desc: 'Local tortoise-tts server', logo: 'tortoise.png', textIcon: 'TT', color: '#7C3AED', isLocal: true },
            { id: 'inworld', name: 'Inworld TTS', desc: 'Inworld character voice API', logo: 'inworld.png', textIcon: 'IW', color: '#FF6B6B' }
        ],
        stt: [
            { id: 'gemini', name: 'Gemini', desc: 'Gemini 2.5 Flash transcribe', logo: 'gemini.png', textIcon: 'GE', color: '#4285F4' },
            { id: 'openai', name: 'OpenAI', desc: 'OpenAI Whisper-1 model', logo: 'openai.png', textIcon: 'OA', color: '#10A37F' },
            { id: 'groq', name: 'Groq', desc: 'Whisper Whisper-1 (Fastest)', logo: 'groq.png', textIcon: 'GQ', color: '#F55036' },
            { id: 'deepgram', name: 'Deepgram', desc: 'Nova 3 / Nova 2 speech models', logo: 'deepgram.png', textIcon: 'DG', color: '#13EF93' },
            { id: 'assemblyai', name: 'AssemblyAI', desc: 'Universal 3 Pro speech recognition', logo: 'assemblyai.png', textIcon: 'AA', color: '#0062FF' },
            { id: 'huggingface', name: 'HuggingFace', desc: 'Whisper models on Hub', logo: 'huggingface.png', textIcon: 'HF', color: '#FFD21E' }
        ],
        video: [
            { id: 'runway', name: 'Runway Gen-2', desc: 'Runway text-to-video API', logo: 'runwayml.png', textIcon: 'RW', color: '#FF007F', isBuiltIn: true },
            { id: 'luma', name: 'Luma Dream Machine', desc: 'Dream Machine video API', logo: 'topaz.png', textIcon: 'LM', color: '#1A1A1A', isBuiltIn: true },
            { id: 'sora', name: 'OpenAI Sora', desc: 'High-fidelity video models', logo: 'openai.png', textIcon: 'SO', color: '#10A37F', isBuiltIn: true },
            { id: 'kling', name: 'Kling AI', desc: 'Kling video generation', logo: 'kling.png', textIcon: 'KL', color: '#E53E3E', isBuiltIn: true },
            { id: 'hailuo', name: 'Hailuo MiniMax', desc: 'MiniMax Video API', logo: 'hailuo.png', textIcon: 'HL', color: '#3182CE', isBuiltIn: true }
        ]
    };

    window.renderMediaProviders = async function() {
        let providersData = {};
        try {
            const res = await fetch('/api/config');
            if (res.ok) {
                const config = await res.json();
                providersData = config.providers || {};
            }
        } catch (e) {
            console.error('Failed to load active providers for status badges:', e);
        }

        Object.keys(MEDIA_PROVIDERS).forEach(kind => {
            const grid = document.getElementById('grid-media-' + kind);
            if (!grid) return;
            
            grid.innerHTML = '';
            MEDIA_PROVIDERS[kind].forEach(p => {
                const card = document.createElement('div');
                card.className = 'provider-card p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col justify-between hover:shadow-md hover:border-slate-350 dark:hover:border-slate-700 cursor-pointer transition-all duration-200';
                
                let badgeText = 'READY';
                let badgeClass = 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-900/50';
                let hasDetailView = false;
                
                if (p.isBuiltIn) {
                    badgeText = 'READY';
                    badgeClass = 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-900/50';
                } else if (p.isLocal) {
                    badgeText = 'READY';
                    badgeClass = 'bg-blue-50 dark:bg-blue-950/20 text-blue-600 dark:text-blue-400 border-blue-100 dark:border-blue-900/50';
                } else {
                    hasDetailView = true;
                    const provConfig = providersData[p.id] || {};
                    const connections = provConfig.connections || [];
                    const activeCount = connections.filter(c => c.enabled).length;
                    
                    if (connections.length === 0) {
                        badgeText = 'No connections';
                        badgeClass = 'bg-slate-50 dark:bg-slate-800/40 text-slate-500 dark:text-slate-400 border-slate-100 dark:border-slate-800';
                    } else if (activeCount === 0) {
                        badgeText = 'Disabled';
                        badgeClass = 'bg-rose-50 dark:bg-rose-950/20 text-rose-600 dark:text-rose-400 border-rose-100 dark:border-rose-900/50';
                    } else {
                        badgeText = `${activeCount} Connected`;
                        badgeClass = 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-900/50';
                    }
                }
                
                const isChecked = p.isBuiltIn || p.isLocal || (badgeText.includes('Connected'));
                const provConfig = providersData[p.id] || {};
                const connections = provConfig.connections || [];

                card.innerHTML = `
                    <div class="flex items-start justify-between mb-4">
                        <div class="w-10 h-10 rounded-xl flex items-center justify-center p-1.5 bg-slate-50 dark:bg-slate-950 border border-slate-100 dark:border-slate-805 shrink-0">
                            <img class="w-full h-full object-contain rounded-md" src="/static/Images/providers/${p.logo}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" alt="">
                            <div class="hidden w-full h-full items-center justify-center rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-bold text-slate-500" style="display:none">${p.textIcon || p.name.slice(0,2).toUpperCase()}</div>
                        </div>
                        <div class="flex items-center gap-2" onclick="event.stopPropagation()">
                            <span class="px-2.5 py-0.5 text-[10px] font-semibold rounded-full border ${badgeClass}">
                                ${badgeText}
                            </span>
                            <label class="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" ${isChecked ? 'checked' : ''} onchange="${connections.length > 0 && typeof window.toggleAllConnections === 'function' ? `toggleAllConnections('${p.id}', this.checked)` : `switchPage('providers'); if (typeof window.showDetailView === 'function') window.showDetailView('${p.id}');`}" class="sr-only peer">
                                <div class="w-7 h-4 bg-slate-200 dark:bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-350 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-orange-500"></div>
                            </label>
                        </div>
                    </div>
                    <div class="space-y-1">
                        <h3 class="font-bold text-[14px] text-slate-800 dark:text-slate-200">${p.name}</h3>
                        <p class="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-2">${p.desc}</p>
                    </div>
                `;
                
                card.onclick = () => {
                    switchPage('providers');
                    if (typeof window.showDetailView === 'function') {
                        window.showDetailView(p.id);
                    }
                };
                
                grid.appendChild(card);
            });
        });
    };

    // Auto load status when navigation occurs
    const originalSwitchPage = window.switchPage;
    window.switchPage = function(name) {
        if (originalSwitchPage) originalSwitchPage(name);
        if (name.startsWith('media-')) {
            window.renderMediaProviders();
        }
    };
})();
