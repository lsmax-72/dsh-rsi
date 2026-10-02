// Local extraction diagnostics use the caller's logger; no /data/log side effect.
export const obsLogger = {
  info(_event: string, _attrs?: unknown) {},
  warn(_event: string, _attrs?: unknown) {},
  error(_event: string, _attrs?: unknown, _error?: unknown) {},
};
