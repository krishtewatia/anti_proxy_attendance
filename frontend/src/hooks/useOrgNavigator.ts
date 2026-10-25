import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../services";
import type { OrgStructure } from "../utils/organisation.ts";
import { loadSelection, navYears, saveSelection, validSelection, type NavSelection } from "../utils/orgNavigator.ts";

// The organisation structure and the admin's current Year > Branch > Section
// choice (remembered in this browser). `pilot` is false on a database without
// the pilot structure, where the older flat screens are used instead.
export function useOrgNavigator() {
  const [structure, setStructure] = useState<OrgStructure | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [selection, setSelectionState] = useState<NavSelection>(loadSelection);

  const reload = useCallback(async () => {
    try {
      setStructure(await api.getOrgStructure());
    } catch {
      setStructure(null);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const years = useMemo(() => navYears(structure), [structure]);
  const current = useMemo(() => validSelection(years, selection), [years, selection]);

  const setSelection = useCallback((next: NavSelection) => {
    setSelectionState(next);
    saveSelection(next);
  }, []);

  return { structure, years, selection: current, setSelection, loaded, pilot: years.length > 0, reload };
}
