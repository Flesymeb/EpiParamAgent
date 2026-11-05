/** Read the effective editor value without letting backend defaults hide data. */
export function readAnalysisProtocol(task: Record<string, unknown>): unknown {
  const multiple = task.analysis_protocols;
  if (Array.isArray(multiple) && multiple.length > 0) return multiple;
  return task.analysis_protocol ?? multiple ?? {};
}

/** Update only analysis configuration, preserving unrelated advanced task fields. */
export function writeAnalysisProtocol(
  task: Record<string, unknown>,
  value: unknown,
): Record<string, unknown> {
  const next = { ...task };
  if (Array.isArray(value)) {
    next.analysis_protocols = value;
    delete next.analysis_protocol;
  } else {
    next.analysis_protocol = value;
    delete next.analysis_protocols;
  }
  return next;
}
