'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';
import { errorMessage } from '@/lib/utils';

interface SettingsForm {
  llm_provider: string;
  llm_model: string;
  llm_api_key: string;
  llm_ollama_url: string;
  summary_language: string;
}

const SUMMARY_LANGUAGES = [
  { code: '', label: 'source language (follow transcript)' },
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'French' },
  { code: 'es', label: 'Spanish' },
  { code: 'de', label: 'German' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'it', label: 'Italian' },
  { code: 'nl', label: 'Dutch' },
  { code: 'ru', label: 'Russian' },
  { code: 'ja', label: 'Japanese' },
  { code: 'ko', label: 'Korean' },
  { code: 'zh-cn', label: 'Chinese (Simplified)' },
  { code: 'ar', label: 'Arabic' },
  { code: 'hi', label: 'Hindi' },
  { code: 'tr', label: 'Turkish' },
];

const DEFAULT_MODELS: Record<string, string> = {
  anthropic: 'claude-sonnet-4-6',
  openai: 'gpt-4o-mini',
  ollama: 'qwen3:8b',
  vllm: 'gemma4-31b',
  deepseek: 'deepseek-chat',
  minimax: 'MiniMax-Text-01',
  opencode: '',
};

interface VLLMFleetNode {
  id: string;
  label: string;
  tier: string;
  desc: string;
  model: string;
  url: string;
}

const INPUT_CLASS = 'px-3 h-10 border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light text-[13px] focus:outline-none focus:ring-2 focus:ring-primary';
const LABEL_CLASS = 'block text-[13px] font-semibold text-text-dark dark:text-text-light mb-2';

interface CloudProviderFieldsProps {
  apiKeyPlaceholder: string;
  modelPlaceholder: string;
  form: SettingsForm;
  hasApiKey?: boolean;
  saving: boolean;
  onApiKeyChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onModelChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onClearApiKey: () => void;
}

function CloudProviderFields({
  apiKeyPlaceholder, modelPlaceholder, form, hasApiKey, saving,
  onApiKeyChange, onModelChange, onClearApiKey,
}: CloudProviderFieldsProps) {
  return (
    <>
      <div>
        <label className={LABEL_CLASS}>
          api key
          {hasApiKey && (
            <span className="ml-2 inline-block bg-success/20 text-success text-xs px-2 py-0.5 rounded">key saved</span>
          )}
        </label>
        <div className="flex gap-2">
          <input
            type="password"
            value={form.llm_api_key}
            onChange={onApiKeyChange}
            placeholder={apiKeyPlaceholder}
            className={`flex-1 ${INPUT_CLASS}`}
          />
          {hasApiKey && (
            <button
              type="button"
              onClick={onClearApiKey}
              disabled={saving}
              className="px-3 h-10 bg-red-100 hover:bg-red-200 dark:bg-red-900/30 dark:hover:bg-red-900/50 text-red-700 dark:text-red-400 rounded-lg text-[13px] font-medium transition-colors disabled:opacity-50"
            >
              clear
            </button>
          )}
        </div>
      </div>
      <div>
        <label className={LABEL_CLASS}>model name</label>
        <input
          type="text"
          value={form.llm_model}
          onChange={onModelChange}
          placeholder={modelPlaceholder}
          className={`w-full ${INPUT_CLASS}`}
        />
      </div>
    </>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuthStore();

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [vllmFleet, setVllmFleet] = useState<VLLMFleetNode[]>([]);
  const [vllmModelFetching, setVllmModelFetching] = useState(false);
  const [vllmAvailableModels, setVllmAvailableModels] = useState<string[]>([]);

  const [form, setForm] = useState<SettingsForm>({
    llm_provider: user?.llm_provider || 'ollama',
    llm_model: user?.llm_model || DEFAULT_MODELS['ollama'],
    llm_api_key: '',
    llm_ollama_url: '',
    summary_language: '',
  });

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [authLoading, isAuthenticated, router]);

  useEffect(() => {
    if (!isAuthenticated || !user) return;

    const fetchSettings = async () => {
      try {
        setLoading(true);
        const [settingsRes, fleetRes] = await Promise.allSettled([
          apiClient.get('/settings/me'),
          apiClient.get('/settings/vllm/fleet'),
        ]);

        const settings = settingsRes.status === 'fulfilled' ? settingsRes.value.data : {};
        const fleet: VLLMFleetNode[] = fleetRes.status === 'fulfilled' ? (fleetRes.value.data.nodes ?? []) : [];
        setVllmFleet(fleet);

        const provider = settings.llm_provider || 'ollama';
        const savedUrl = settings.llm_ollama_url || '';

        setForm({
          llm_provider: provider,
          llm_model: settings.llm_model || DEFAULT_MODELS[provider] || '',
          llm_api_key: '',
          llm_ollama_url: savedUrl,
          summary_language: settings.summary_language || '',
        });

        if (settingsRes.status !== 'fulfilled') {
          setError('Failed to load settings');
        }

        if (provider === 'vllm' && savedUrl) {
          setVllmModelFetching(true);
          try {
            const res = await apiClient.get('/settings/vllm/models', { params: { base_url: savedUrl } });
            setVllmAvailableModels(res.data.models ?? []);
          } catch {
            // sidecar unreachable — text input still shows saved model name
          } finally {
            setVllmModelFetching(false);
          }
        }
      } catch (err: any) {
        console.error('Failed to load settings:', err);
        setError('Failed to load settings');
      } finally {
        setLoading(false);
      }
    };

    fetchSettings();
  }, [isAuthenticated, user]);

  const handleProviderChange = (provider: string) => {
    setForm((prev) => ({
      ...prev,
      llm_provider: provider,
      llm_model: DEFAULT_MODELS[provider] || '',
    }));
  };

  const handleModelChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({
      ...prev,
      llm_model: e.target.value,
    }));
  };

  const handleApiKeyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({
      ...prev,
      llm_api_key: e.target.value,
    }));
  };

  const handleOllamaUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({
      ...prev,
      llm_ollama_url: e.target.value,
    }));
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setSaving(true);

    try {
      const payload: any = {
        llm_provider: form.llm_provider,
        llm_model: form.llm_model,
        summary_language: form.summary_language || '',
      };

      // Include base URL for providers that need a custom endpoint
      if ((form.llm_provider === 'ollama' || form.llm_provider === 'vllm' || form.llm_provider === 'opencode') && form.llm_ollama_url.trim()) {
        payload.llm_ollama_url = form.llm_ollama_url;
      }

      // Only include API key if it's not empty
      if (form.llm_api_key.trim()) {
        payload.llm_api_key = form.llm_api_key;
      }

      const response = await apiClient.patch('/settings/me', payload);

      setSuccess('Settings saved successfully!');
      setForm((prev) => ({
        ...prev,
        llm_api_key: '',
      }));

      try {
        const userRes = await apiClient.get('/auth/me');
        useAuthStore.setState({ user: userRes.data });
      } catch {
        // Ignore errors refreshing user
      }

      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      setError(errorMessage(err, 'Failed to save settings'));
    } finally {
      setSaving(false);
    }
  };

  const handleClearApiKey = async () => {
    if (!confirm('Are you sure you want to clear the stored API key?')) return;

    try {
      setSaving(true);
      await apiClient.delete('/settings/me/api-key');
      setSuccess('API key cleared successfully');
      setForm((prev) => ({
        ...prev,
        llm_api_key: '',
      }));

      try {
        const userRes = await apiClient.get('/auth/me');
        useAuthStore.setState({ user: userRes.data });
      } catch {
        // Ignore errors refreshing user
      }

      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      setError(errorMessage(err, 'Failed to clear API key'));
    } finally {
      setSaving(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-bg-light dark:bg-bg-dark flex items-center justify-center">
        <div className="text-text-muted">loading settings...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg-light dark:bg-bg-dark">
      <div className="max-w-2xl mx-auto px-4 py-12 flex flex-col gap-10">

        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        {success && (
          <div className="mb-6 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-green-700 dark:text-green-400 flex items-center gap-2">
            <span>✓</span>
            <span>{success}</span>
          </div>
        )}

        <form onSubmit={handleSave} className="flex flex-col gap-10 max-w-[500px]">
          <div className="flex flex-col gap-6">
            <div>
              <h2 className="text-2xl font-semibold text-text-dark dark:text-text-light">
                llm provider
              </h2>
              <p className="text-sm text-text-muted mt-1">
                choose your preferred llm provider for document summarization
              </p>
            </div>

            {/* Provider Cards — radio group for keyboard accessibility */}
            <div className="flex flex-col gap-4" role="radiogroup" aria-label="llm provider">

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'ollama' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="ollama"
                    checked={form.llm_provider === 'ollama'}
                    onChange={() => handleProviderChange('ollama')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'ollama' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'ollama' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">ollama</p>
                    <p className="text-xs text-text-muted">local, private, no api key required</p>
                  </div>
                </label>
                {form.llm_provider === 'ollama' && (
                  <>
                    <div>
                      <label className={LABEL_CLASS}>base url</label>
                      <input
                        type="url"
                        value={form.llm_ollama_url}
                        onChange={handleOllamaUrlChange}
                        placeholder="http://localhost:11434"
                        className={`w-full ${INPUT_CLASS}`}
                      />
                    </div>
                    <div>
                      <label className={LABEL_CLASS}>model name</label>
                      <input
                        type="text"
                        value={form.llm_model}
                        onChange={handleModelChange}
                        placeholder="qwen3:8b (leave empty for default)"
                        className={`w-full ${INPUT_CLASS}`}
                      />
                    </div>
                  </>
                )}
              </div>

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'openai' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="openai"
                    checked={form.llm_provider === 'openai'}
                    onChange={() => handleProviderChange('openai')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'openai' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'openai' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">openai</p>
                    <p className="text-xs text-text-muted">gpt-4o-mini (requires api key)</p>
                  </div>
                </label>
                {form.llm_provider === 'openai' && (
                  <CloudProviderFields
                    apiKeyPlaceholder="sk-..."
                    modelPlaceholder={DEFAULT_MODELS['openai']}
                    form={form}
                    hasApiKey={user?.has_api_key}
                    saving={saving}
                    onApiKeyChange={handleApiKeyChange}
                    onModelChange={handleModelChange}
                    onClearApiKey={handleClearApiKey}
                  />
                )}
              </div>

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'anthropic' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="anthropic"
                    checked={form.llm_provider === 'anthropic'}
                    onChange={() => handleProviderChange('anthropic')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'anthropic' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'anthropic' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">anthropic</p>
                    <p className="text-xs text-text-muted">claude sonnet 4.6 (requires api key)</p>
                  </div>
                </label>
                {form.llm_provider === 'anthropic' && (
                  <CloudProviderFields
                    apiKeyPlaceholder="sk-ant-..."
                    modelPlaceholder={DEFAULT_MODELS['anthropic']}
                    form={form}
                    hasApiKey={user?.has_api_key}
                    saving={saving}
                    onApiKeyChange={handleApiKeyChange}
                    onModelChange={handleModelChange}
                    onClearApiKey={handleClearApiKey}
                  />
                )}
              </div>

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'deepseek' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="deepseek"
                    checked={form.llm_provider === 'deepseek'}
                    onChange={() => handleProviderChange('deepseek')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'deepseek' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'deepseek' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">deepseek</p>
                    <p className="text-xs text-text-muted">deepseek-chat · api.deepseek.com (requires api key)</p>
                  </div>
                </label>
                {form.llm_provider === 'deepseek' && (
                  <CloudProviderFields
                    apiKeyPlaceholder="sk-..."
                    modelPlaceholder={DEFAULT_MODELS['deepseek']}
                    form={form}
                    hasApiKey={user?.has_api_key}
                    saving={saving}
                    onApiKeyChange={handleApiKeyChange}
                    onModelChange={handleModelChange}
                    onClearApiKey={handleClearApiKey}
                  />
                )}
              </div>

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'minimax' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="minimax"
                    checked={form.llm_provider === 'minimax'}
                    onChange={() => handleProviderChange('minimax')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'minimax' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'minimax' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">minimax</p>
                    <p className="text-xs text-text-muted">MiniMax-Text-01 · api.minimaxi.chat (requires api key)</p>
                  </div>
                </label>
                {form.llm_provider === 'minimax' && (
                  <CloudProviderFields
                    apiKeyPlaceholder="eyJ..."
                    modelPlaceholder={DEFAULT_MODELS['minimax']}
                    form={form}
                    hasApiKey={user?.has_api_key}
                    saving={saving}
                    onApiKeyChange={handleApiKeyChange}
                    onModelChange={handleModelChange}
                    onClearApiKey={handleClearApiKey}
                  />
                )}
              </div>

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'opencode' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="opencode"
                    checked={form.llm_provider === 'opencode'}
                    onChange={() => handleProviderChange('opencode')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'opencode' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'opencode' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">opencode</p>
                    <p className="text-xs text-text-muted">any openai-compatible endpoint · bring your own model + key</p>
                  </div>
                </label>
                {form.llm_provider === 'opencode' && (
                  <>
                    <div>
                      <label className={LABEL_CLASS}>base url</label>
                      <input
                        type="text"
                        value={form.llm_ollama_url}
                        onChange={(e) => setForm((prev) => ({ ...prev, llm_ollama_url: e.target.value }))}
                        placeholder="https://api.minimaxi.chat/v1"
                        className={`w-full ${INPUT_CLASS}`}
                      />
                    </div>
                    <CloudProviderFields
                      apiKeyPlaceholder="sk-..."
                      modelPlaceholder="enter model name (e.g. MiniMax-Text-01)"
                      form={form}
                      hasApiKey={user?.has_api_key}
                      saving={saving}
                      onApiKeyChange={handleApiKeyChange}
                      onModelChange={handleModelChange}
                      onClearApiKey={handleClearApiKey}
                    />
                  </>
                )}
              </div>

              <div className={`rounded-xl p-5 flex flex-col gap-4 bg-card-light dark:bg-card-dark transition-colors ${form.llm_provider === 'vllm' ? 'ring-2 ring-primary' : ''}`}>
                <label className="flex items-center gap-4 cursor-pointer">
                  <input
                    type="radio"
                    name="llm_provider"
                    value="vllm"
                    checked={form.llm_provider === 'vllm'}
                    onChange={() => handleProviderChange('vllm')}
                    className="sr-only"
                  />
                  <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 ${form.llm_provider === 'vllm' ? 'border-primary' : 'border-text-muted'}`}>
                    {form.llm_provider === 'vllm' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-text-dark dark:text-text-light">vllm</p>
                    <p className="text-xs text-text-muted">self-hosted vllm fleet, openai-compatible, no api key required</p>
                  </div>
                </label>
                {form.llm_provider === 'vllm' && (
                  <>
                    <div className="flex flex-col gap-2">
                      <label className={LABEL_CLASS}>fleet node</label>
                      <div className="grid grid-cols-2 gap-2">
                        {vllmFleet.length === 0 && (
                          <p className="col-span-2 text-[13px] text-text-muted">no fleet nodes configured</p>
                        )}
                        {vllmFleet.map((node) => {
                          const selected = form.llm_ollama_url === node.url;
                          return (
                            <button
                              key={node.id}
                              type="button"
                              onClick={async () => {
                                setForm((prev) => ({ ...prev, llm_ollama_url: node.url, llm_model: '' }));
                                setVllmAvailableModels([]);
                                setVllmModelFetching(true);
                                try {
                                  const res = await apiClient.get('/settings/vllm/models', { params: { base_url: node.url } });
                                  const models: string[] = [...new Set<string>(res.data.models ?? [])];
                                  setVllmAvailableModels(models);
                                  if (models.length === 1) {
                                    setForm((prev) => ({ ...prev, llm_model: models[0] }));
                                  }
                                } catch {
                                  // sidecar unreachable — leave model empty
                                } finally {
                                  setVllmModelFetching(false);
                                }
                              }}
                              className={`text-left px-3 py-2.5 rounded-lg border transition-colors ${
                                selected
                                  ? 'border-primary bg-primary/10 text-text-dark dark:text-text-light'
                                  : 'border-border-light dark:border-transparent bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light hover:border-primary/50'
                              }`}
                            >
                              <p className="text-[13px] font-semibold">{node.label}</p>
                              <p className="text-[11px] text-text-muted">{node.tier}</p>
                              <p className="text-[11px] text-text-muted">{node.desc}</p>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    {form.llm_ollama_url && (
                      <div className="flex flex-col gap-2">
                        <label className={LABEL_CLASS}>model</label>
                        {vllmModelFetching ? (
                          <p className="text-[13px] text-text-muted">fetching from sidecar...</p>
                        ) : vllmAvailableModels.length > 0 && (
                          <div className="flex flex-col gap-1">
                            {vllmAvailableModels.map((m) => (
                              <button
                                key={m}
                                type="button"
                                onClick={() => setForm((prev) => ({ ...prev, llm_model: m }))}
                                className={`text-left px-3 py-2 rounded-lg border text-[13px] transition-colors ${
                                  form.llm_model === m
                                    ? 'border-primary bg-primary/10 text-text-dark dark:text-text-light'
                                    : 'border-border-light dark:border-transparent bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light hover:border-primary/50'
                                }`}
                              >
                                {m}
                              </button>
                            ))}
                          </div>
                        )}
                        <input
                          type="text"
                          value={form.llm_model}
                          onChange={handleModelChange}
                          placeholder="or type a model name to load on first request"
                          className={`w-full ${INPUT_CLASS}`}
                        />
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-6">
            <div>
              <h2 className="text-2xl font-semibold text-text-dark dark:text-text-light">
                summary language
              </h2>
              <p className="text-sm text-text-muted mt-1">
                choose the output language for llm summaries (independent of the video&apos;s spoken language)
              </p>
            </div>
            <div className="rounded-xl p-5 bg-card-light dark:bg-card-dark">
              <label className={LABEL_CLASS}>output language</label>
              <select
                value={form.summary_language}
                onChange={(e) => setForm((prev) => ({ ...prev, summary_language: e.target.value }))}
                className={`w-full ${INPUT_CLASS}`}
              >
                {SUMMARY_LANGUAGES.map(({ code, label }) => (
                  <option key={code} value={code}>{label}</option>
                ))}
              </select>
            </div>
          </div>

          <button
            type="submit"
            disabled={saving}
            className="w-full bg-accent-orange hover:opacity-90 disabled:opacity-50 text-white font-semibold h-12 rounded-lg transition-colors"
          >
            {saving ? 'saving...' : 'save settings'}
          </button>
        </form>
      </div>
    </div>
  );
}
