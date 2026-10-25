import React, { useEffect, useState } from "react";
import { api } from "../../services";
import { ConsentNotice } from "../auth/ConsentNotice";
import type { ConsentNotice as Notice } from "../../utils/registration.ts";
import {
  BLURRY_BELOW,
  SETUP_STEPS,
  choiceLabel,
  cohortOf,
  coreClasses,
  requestBody,
  sharpness,
  stepProblem,
  type PhotoCheckResult,
  type SetupDraft,
  type SetupOptions,
} from "../../utils/enrolment.ts";

interface SetupWizardProps {
  initial: SetupDraft;
  isChange: boolean;
  onDone: (message: string) => void;
  onCancel: () => void;
}

interface PhotoEntry {
  data: string;
  check: PhotoCheckResult | null;
  blurry: boolean;
  checking: boolean;
}

const MAX_SIDE = 960;

// Shrinks a photo to at most 960 px and measures its sharpness in the browser.
async function preparePhoto(file: File): Promise<{ data: string; blurry: boolean }> {
  const url = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("This file is not a photo."));
      img.src = url;
    });
    const scale = Math.min(1, MAX_SIDE / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser cannot read photos.");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);

    const small = document.createElement("canvas");
    small.width = 240;
    small.height = Math.max(3, Math.round((240 * canvas.height) / canvas.width));
    const smallContext = small.getContext("2d");
    let blurry = false;
    if (smallContext) {
      smallContext.drawImage(canvas, 0, 0, small.width, small.height);
      const pixels = smallContext.getImageData(0, 0, small.width, small.height).data;
      const gray = new Float32Array(small.width * small.height);
      for (let i = 0; i < gray.length; i++) gray[i] = 0.299 * pixels[i * 4] + 0.587 * pixels[i * 4 + 1] + 0.114 * pixels[i * 4 + 2];
      blurry = sharpness(gray, small.width, small.height) < BLURRY_BELOW;
    }
    return { data: canvas.toDataURL("image/jpeg", 0.9), blurry };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// The student's setup: year and section, core subjects, electives and DLDA
// group (by code only), 2-3 checked face photos, then one request for approval.
export const SetupWizard: React.FC<SetupWizardProps> = ({ initial, isChange, onDone, onCancel }) => {
  const [options, setOptions] = useState<SetupOptions | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [draft, setDraft] = useState<SetupDraft>(initial);
  const [photos, setPhotos] = useState<PhotoEntry[]>([]);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getSetupOptions(), api.getRegistrationRules()])
      .then(([loaded, rules]) => {
        if (cancelled) return;
        setOptions(loaded);
        setNotice(rules.consent_notice);
        // A single year is chosen for the student.
        if (loaded.cohorts.length === 1) setDraft((d) => (d.cohortId ? d : { ...d, cohortId: loaded.cohorts[0].cohort_id }));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(`Could not load the choices: ${errorText(err)}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const cohort = cohortOf(options, draft.cohortId);
  const current = { ...draft, photos: photos.map((p) => p.data) };
  const problem = stepProblem(step, current, options, isChange);
  const photoLimits = options?.photos ?? { min: 2, max: 3 };

  const addPhoto = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      const prepared = await preparePhoto(file);
      const entry: PhotoEntry = { data: prepared.data, blurry: prepared.blurry, check: null, checking: true };
      setPhotos((list) => [...list, entry]);
      let check: PhotoCheckResult | null = null;
      try {
        check = await api.checkSetupPhoto(prepared.data);
      } catch (err: unknown) {
        setError(`The photo could not be checked: ${errorText(err)}`);
      }
      setPhotos((list) => list.map((p) => (p === entry ? { ...p, check, checking: false } : p)));
    } catch (err: unknown) {
      setError(errorText(err));
    }
  };

  const removePhoto = (index: number) => setPhotos((list) => list.filter((_, i) => i !== index));

  const next = () => {
    if (problem) {
      setError(problem);
      return;
    }
    if (step === 3 && photos.some((p) => p.check && !p.check.ok)) {
      setError("Remove the photos that did not pass the check and add better ones.");
      return;
    }
    setError(null);
    setStep((s) => Math.min(s + 1, SETUP_STEPS.length - 1));
  };

  const submit = async () => {
    const finalProblem = stepProblem(SETUP_STEPS.length - 1, current, options, isChange);
    if (finalProblem || !options) {
      setError(finalProblem ?? "The choices are still loading.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      await api.submitSetup(requestBody(current, options.consent_version));
      onDone(isChange ? "Your change was sent for approval." : "Your setup was sent for approval.");
    } catch (err: unknown) {
      setError(errorText(err));
    } finally {
      setSending(false);
    }
  };

  const setChoice = (setCode: string, option: string, group: string) =>
    setDraft((d) => ({ ...d, choices: { ...d.choices, [setCode]: { option, group } } }));

  return (
    <div className="erp-card" style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "1.25rem" }}>
        {SETUP_STEPS.map((label, index) => (
          <span key={label} className={`status-badge ${index === step ? "present" : index < step ? "completed" : ""}`}>
            {index + 1}. {label}
          </span>
        ))}
      </div>

      {error && (
        <div className="alert-banner error" role="alert" style={{ marginBottom: "1rem" }}>
          <span>{typeof error === "string" ? error : "Something went wrong."}</span>
        </div>
      )}

      {!options && !error && <p style={{ color: "var(--erp-text-muted)" }}>Loading the choices...</p>}

      {options && step === 0 && (
        <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
          <div className="form-group">
            <label className="form-label" htmlFor="setup-year">Year</label>
            <select
              id="setup-year"
              className="erp-select-input"
              value={draft.cohortId}
              onChange={(e) => setDraft({ ...draft, cohortId: e.target.value, section: "", choices: {} })}
            >
              <option value="">Choose your year</option>
              {options.cohorts.map((c) => (
                <option key={c.cohort_id} value={c.cohort_id}>{c.name}</option>
              ))}
            </select>
          </div>
          {cohort && (
            <div className="form-group">
              <span className="form-label">Section</span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                {cohort.sections.map((s) => (
                  <button
                    key={s.code}
                    type="button"
                    className={`erp-btn ${draft.section === s.code ? "erp-btn-primary" : "erp-btn-secondary"}`}
                    onClick={() => setDraft({ ...draft, section: s.code })}
                    aria-pressed={draft.section === s.code}
                  >
                    Section {s.code}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {options && step === 1 && (
        <div>
          <p style={{ color: "var(--erp-text-muted)", fontSize: "0.875rem", marginTop: 0 }}>
            These are the subjects of Section {draft.section}. They come from the section's timetable.
          </p>
          <div className="erp-table-container">
            <table className="erp-table">
              <thead>
                <tr>
                  <th />
                  <th>Code</th>
                  <th>Subject</th>
                </tr>
              </thead>
              <tbody>
                {coreClasses(options, draft.cohortId, draft.section).map((c) => (
                  <tr key={c.class_id}>
                    <td><input type="checkbox" checked readOnly disabled aria-label={`${c.name} is included`} /></td>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.8125rem" }}>{c.code}</td>
                    <td>{c.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {options.not_counted.length > 0 && (
            <p style={{ color: "var(--erp-text-muted)", fontSize: "0.8rem" }}>
              Not counted here: {options.not_counted.map((s) => s.name).join(", ")}.
            </p>
          )}
        </div>
      )}

      {options && cohort && step === 2 && (
        <div style={{ display: "grid", gap: "1.25rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
          {cohort.group_sets.map((set) => {
            const chosen = draft.choices[set.set_code];
            return (
              <div key={set.set_code} className="form-group">
                <span className="form-label">{set.set_code}: {set.name}</span>
                <div style={{ display: "grid", gap: "0.5rem" }}>
                  {set.options.map((option) => (
                    <div key={option.option_code} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem" }}>
                      <span style={{ minWidth: "11rem", fontSize: "0.875rem" }}>{option.name}</span>
                      {option.groups.map((group) => {
                        const active = chosen?.option === option.option_code && chosen.group === group;
                        return (
                          <button
                            key={group}
                            type="button"
                            className={`erp-btn ${active ? "erp-btn-primary" : "erp-btn-secondary"}`}
                            style={{ padding: "0.35rem 0.75rem" }}
                            onClick={() => setChoice(set.set_code, option.option_code, group)}
                            aria-pressed={active}
                          >
                            {group}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {options && step === 3 && (
        <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
          {isChange && (
            <p style={{ margin: 0, color: "var(--erp-text-muted)", fontSize: "0.875rem" }}>
              Photos are optional for a change. Add new ones only if you want to replace your current photos.
            </p>
          )}
          {notice && (
            <ConsentNotice notice={notice} accepted={draft.consentAccepted} onChange={(v) => setDraft({ ...draft, consentAccepted: v })} />
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
            {photos.map((photo, index) => (
              <div key={index} style={{ width: "140px", fontSize: "0.75rem" }}>
                <img src={photo.data} alt={`Photo ${index + 1}`} style={{ width: "140px", height: "140px", objectFit: "cover", borderRadius: "8px", border: "1px solid var(--erp-border)" }} />
                {photo.checking && <div style={{ color: "var(--erp-text-muted)" }}>Checking...</div>}
                {photo.check?.ok && <span className="status-badge present">Good</span>}
                {photo.check && !photo.check.ok && (
                  <div className="text-shortage">{photo.check.problems.join(" ")}</div>
                )}
                {photo.blurry && photo.check?.ok && <div style={{ color: "var(--erp-text-muted)" }}>Looks a little blurry; a sharper photo is better.</div>}
                <button type="button" className="erp-btn erp-btn-secondary" style={{ padding: "0.25rem 0.5rem", marginTop: "0.25rem" }} onClick={() => removePhoto(index)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
          {photos.length < photoLimits.max && (
            <label className="erp-btn erp-btn-secondary" style={{ justifySelf: "start", cursor: draft.consentAccepted ? "pointer" : "not-allowed", opacity: draft.consentAccepted ? 1 : 0.6 }}>
              {draft.consentAccepted ? "Take or choose a photo" : "Accept the notice to add photos"}
              <input
                type="file"
                accept="image/*"
                capture="user"
                disabled={!draft.consentAccepted}
                style={{ display: "none" }}
                onChange={(e) => {
                  void addPhoto(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
          )}
          <p style={{ margin: 0, color: "var(--erp-text-muted)", fontSize: "0.8rem" }}>
            {photoLimits.min} or {photoLimits.max} photos: only your face, looking at the camera, in good light, filling most of the photo.
          </p>
        </div>
      )}

      {options && cohort && step === 4 && (
        <div style={{ display: "grid", gap: "0.5rem", fontSize: "0.875rem" }}>
          <div><strong>{cohort.name}</strong>, Section {draft.section}</div>
          {cohort.group_sets.map((set) => (
            <div key={set.set_code}>{choiceLabel(set.set_code, draft.choices[set.set_code])}</div>
          ))}
          <div>{photos.length > 0 ? `${photos.length} photos` : "No new photos (your current ones stay)"}</div>
          <p style={{ color: "var(--erp-text-muted)", margin: "0.5rem 0 0" }}>
            {isChange
              ? "Your approved setup stays in use until an administrator approves this change."
              : "You will be on the attendance list once an administrator approves this."}
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", justifyContent: "space-between", marginTop: "1.5rem" }}>
        <button type="button" className="erp-btn erp-btn-secondary" onClick={step === 0 ? onCancel : () => setStep(step - 1)} disabled={sending}>
          {step === 0 ? "Cancel" : "Back"}
        </button>
        {step < SETUP_STEPS.length - 1 ? (
          <button type="button" className="erp-btn erp-btn-primary" onClick={next} disabled={!options}>
            Next
          </button>
        ) : (
          <button type="button" className="erp-btn erp-btn-primary" onClick={() => void submit()} disabled={sending}>
            {sending ? "Sending..." : "Send for approval"}
          </button>
        )}
      </div>
    </div>
  );
};
