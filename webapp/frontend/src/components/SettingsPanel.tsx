import { useEffect, useState } from "react";
import { LoaderCircle, Save } from "lucide-react";
import { body, moduleLabels, request } from "../api";
import type { Config, ModuleName, Runtime } from "../api";
import { json } from "../utils";
import { ErrorMessage } from "./ui";

export function SettingsPanel({
  action,
  busy,
  onSaved,
}: {
  action: (name: string, fn: () => Promise<void>) => Promise<void>;
  busy: string;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState("");
  const [mineruKey, setMineruKey] = useState("");
  useEffect(() => {
    let live = true;
    void request<Config>("/config")
      .then((c) => {
        if (live) setConfig(c);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, []);
  function edit(module: ModuleName, fields: Partial<Runtime>) {
    if (config)
      setConfig({
        ...config,
        modules: {
          ...config.modules,
          [module]: { ...config.modules[module], ...fields },
        },
      });
  }
  async function save() {
    if (!config) return;
    await action("settings", async () => {
      const modules = Object.fromEntries(
        Object.entries(config.modules).map(([name, r]) => [
          name,
          {
            provider: r.provider,
            ...(r.model?.trim() ? { model: r.model } : {}),
            ...(r.api_base?.trim() ? { api_base: r.api_base } : {}),
            thinking: r.thinking || null,
            max_tokens: Number(r.max_tokens),
            timeout_s: Number(r.timeout_s),
            ...(r.api_key?.trim() ? { api_key: r.api_key } : {}),
          },
        ]),
      );
      const mineru = {
        ...config.mineru,
        ...(mineruKey.trim() ? { api_key: mineruKey } : {}),
      };
      const value = await request<Config>("/config", body({ modules, mineru }));
      setConfig(value);
      setMineruKey("");
      onSaved();
    });
  }
  if (error) return <ErrorMessage error={error} />;
  if (!config)
    return (
      <div className="loading">
        <LoaderCircle className="spin" size={18} />
        读取实际配置…
      </div>
    );
  return (
    <div className="settings-panel">
      <div className="section-inline">
        <div>
          <h2>四阶段模型</h2>
          <p>
            API Key 只写入、不回显；留空保留已配置凭据。任务 YAML 可作独立覆盖。
          </p>
        </div>
        <button
          className="button primary"
          disabled={!!busy}
          onClick={() => void save()}
        >
          {busy === "settings" ? (
            <LoaderCircle className="spin" size={15} />
          ) : (
            <Save size={15} />
          )}
          保存配置
        </button>
      </div>
      {(["query", "screening", "coding", "synthesis"] as ModuleName[]).map(
        (module, index) => {
          const r = config.modules[module];
          return (
            <section className="runtime-section" key={module}>
              <div className="runtime-label">
                <span className="section-number">0{index + 1}</span>
                <div>
                  <h3>{moduleLabels[module]}</h3>
                  <small>{module.toUpperCase()}</small>
                </div>
                <span
                  className={`key-state ${r.api_key_configured ? "ready" : ""}`}
                >
                  {r.provider_changed
                    ? "保存后解析服务配置"
                    : r.api_key_configured
                      ? "凭据已配置"
                      : "凭据未配置"}
                </span>
              </div>
              <div className="runtime-fields">
                <div className="field-row">
                  <label>
                    Provider
                    <input
                      value={r.provider ?? ""}
                      placeholder="pjlab / selfhosted"
                      onChange={(e) =>
                        edit(module, {
                          provider: e.target.value,
                          model: "",
                          api_base: "",
                          api_key: "",
                          api_key_configured: false,
                          provider_changed: true,
                        })
                      }
                    />
                  </label>
                  <label>
                    Model
                    <input
                      value={r.model ?? ""}
                      placeholder={
                        r.provider_changed ? "留空使用所选服务的模型配置" : ""
                      }
                      onChange={(e) => edit(module, { model: e.target.value })}
                    />
                  </label>
                </div>
                <label>
                  API Base
                  <input
                    value={r.api_base ?? ""}
                    placeholder={
                      r.provider_changed ? "留空使用所选服务的地址配置" : ""
                    }
                    onChange={(e) => edit(module, { api_base: e.target.value })}
                  />
                </label>
                <div className="field-row three">
                  <label>
                    Thinking
                    <select
                      value={r.thinking ?? ""}
                      onChange={(e) =>
                        edit(module, { thinking: e.target.value || null })
                      }
                    >
                      <option value="">继承环境设置</option>
                      <option value="disabled">disabled</option>
                      <option value="enabled">enabled</option>
                    </select>
                  </label>
                  <label>
                    输出 token 上限
                    <input
                      type="number"
                      min="1"
                      value={r.max_tokens ?? ""}
                      onChange={(e) =>
                        edit(module, { max_tokens: Number(e.target.value) })
                      }
                    />
                  </label>
                  <label>
                    超时（秒）
                    <input
                      type="number"
                      min="1"
                      value={r.timeout_s ?? ""}
                      onChange={(e) =>
                        edit(module, { timeout_s: Number(e.target.value) })
                      }
                    />
                  </label>
                </div>
                <label>
                  API Key
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={r.api_key ?? ""}
                    placeholder={
                      r.api_key_configured ? "已配置，留空保留" : "填写凭据"
                    }
                    onChange={(e) => edit(module, { api_key: e.target.value })}
                  />
                </label>
              </div>
            </section>
          );
        },
      )}
      <section className="settings-services">
        <h2>全文解析与来源</h2>
        <label>
          MinerU API Base
          <input
            value={String(config.mineru.base_url ?? "")}
            onChange={(e) =>
              setConfig({
                ...config,
                mineru: { ...config.mineru, base_url: e.target.value },
              })
            }
          />
        </label>
        <label className="spaced">
          MinerU Key
          <input
            type="password"
            autoComplete="new-password"
            value={mineruKey}
            placeholder="留空保留已配置凭据"
            onChange={(e) => setMineruKey(e.target.value)}
          />
        </label>
        <details>
          <summary>来源配置状态</summary>
          <pre className="json-view">{json(config.sources)}</pre>
        </details>
      </section>
    </div>
  );
}
