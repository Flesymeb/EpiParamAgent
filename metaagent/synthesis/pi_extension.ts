/** Explicit, project-owned bridge. No shell or filesystem tools are registered. */
import { spawn } from 'node:child_process';
import { Type } from '@earendil-works/pi-ai';
import { defineTool, type ExtensionAPI } from '@earendil-works/pi-coding-agent';

const actions = ['method_capabilities', 'compute_meta', 'read_skill', 'evidence_search', 'profile', 'query', 'evidence', 'save_plan', 'write_code', 'run_code', 'finalize'];
export default function (pi: ExtensionAPI) {
  pi.registerTool(defineTool({
    name: 'epi_tool', label: 'Epidemiology analysis',
    description: `Controlled analysis workspace tools; no arbitrary shell. Start with profile {} for schema/sample/tool_schema and the exact shared research_question/review_context. Plan arrays MUST be literal JSON arrays [] or [{...}], never {"item":[...]} wrappers or empty strings; no coercion is performed. query {sql: SELECT..., parameters:[], limit:<=200, offset:0}; table estimates has input_id and raw_json plus original fields. evidence {source_id,offset:0,length:<=8000} reads original sources. save_plan {plan:{research_question,estimand:{parameter_type,statistic,population,group,timepoint,endpoint_definition,unit,uncertainty:{type,level}},method:{name,unit},source_mapping:[{source_id,quote}],selection:{selected_input_ids:[...],rationale:string,dependence:{strategy,justification}},transformations:[],assumptions:[],reproduction_status:'reproduction'|'exploratory'|'protocol_pending'|'not_computable',sensitivity:[]}}. Reproduction requires source method quotes; exploratory requires explicit assumptions and sensitivity. write_code {language:'python'|'r',code:string}; generated code reads /inputs/table.jsonl, /inputs/records.sqlite, /sources and /analysis_plan.json and writes /work/result.json. method_capabilities {} lists verified methods; compute_meta {} computes a candidate from saved selection; read_skill {name} returns one analysis manual from the skill list in profile.skills; evidence_search {terms:[literal strings],limit:20} locates source passages. Random effects require tau2 in result and explicit tau/interval declarations. run_code {} executes twice and independently checks supported statistics. finalize {execution_id: the actual run_code ID} validates and publishes results. Use profile tool_schema for complete contracts; never guess source/input/execution IDs.`,
    parameters: Type.Object({
      action: Type.Union(actions.map(action => Type.Literal(action))),
      payload: Type.Record(Type.String(), Type.Unknown()),
    }, { additionalProperties: false }),
    async execute(_id, params, signal) {
      if (!actions.includes(params.action)) throw new Error('Unknown analysis action');
      const workspace = process.env.METAAGENT_SYNTHESIS_WORKSPACE;
      const python = process.env.METAAGENT_SYNTHESIS_PYTHON;
      const project = process.env.METAAGENT_SYNTHESIS_PROJECT;
      if (!workspace || !python || !project) throw new Error('Missing private bridge configuration');
      const env: Record<string, string> = {
        PATH: process.env.PATH || '/usr/bin:/bin',
        LANG: 'C.UTF-8', PYTHONIOENCODING: 'utf-8', PYTHONPATH: project,
        METAAGENT_SYNTHESIS_WORKSPACE: workspace,
      };
      const timeout = Number(process.env.METAAGENT_SYNTHESIS_TOOL_TIMEOUT || '120') * 1000;
      return await new Promise((resolve, reject) => {
        const child = spawn(python, ['-m', 'metaagent.synthesis.pi_tools'], {
          cwd: project, env, stdio: ['pipe', 'pipe', 'pipe'], detached: true,
        });
        let stdout = ''; let stderr = ''; let settled = false;
        const stop = () => { try { process.kill(-child.pid!, 'SIGKILL'); } catch {} };
        const finish = (error?: Error, result?: any) => {
          if (settled) return; settled = true;
          clearTimeout(timer); signal?.removeEventListener('abort', abort);
          if (error) reject(error); else resolve(result);
        };
        const abort = () => { stop(); finish(new Error('Analysis tool aborted')); };
        const timer = setTimeout(() => { stop(); finish(new Error('Analysis tool deadline exceeded')); }, timeout);
        signal?.addEventListener('abort', abort, { once: true });
        if (signal?.aborted) { abort(); return; }
        child.stdout.on('data', chunk => {
          stdout += chunk.toString('utf8');
          if (Buffer.byteLength(stdout) > 16 * 1024 * 1024) { stop(); finish(new Error('Analysis tool result exceeds limit')); }
        });
        // Worker receives no credentials; still never relay unstructured diagnostics to the model.
        child.stderr.on('data', chunk => { if (stderr.length < 4096) stderr += chunk.toString('utf8'); });
        child.on('error', () => finish(new Error('Analysis worker could not start')));
        child.on('close', code => {
          if (settled) return;
          try {
            const result = JSON.parse(stdout);
            if (typeof result.ok !== 'boolean' || (result.action && result.action !== params.action)) throw new Error();
            finish(undefined, { content: [{ type: 'text', text: JSON.stringify(result) }], details: result, isError: !result.ok || code !== 0 });
          } catch { finish(new Error('Analysis worker returned invalid JSON')); }
        });
        child.stdin.on('error', () => {});
        child.stdin.end(JSON.stringify({ action: params.action, payload: params.payload }));
      });
    },
  }));
  pi.on('session_start', async () => { pi.setActiveTools(['epi_tool']); });
}
