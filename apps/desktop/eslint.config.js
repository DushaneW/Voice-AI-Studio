import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import globals from 'globals';
export default tseslint.config(
 {ignores:['dist/**','node_modules/**','src-tauri/**']},
 js.configs.recommended,...tseslint.configs.recommended,
 {languageOptions:{globals:{...globals.browser,...globals.node}}},
 {files:['public/recorder-worklet.js'],languageOptions:{globals:{AudioWorkletProcessor:'readonly',registerProcessor:'readonly'}}},
 {files:['**/*.test.ts','**/*.test.tsx'],rules:{'@typescript-eslint/no-explicit-any':'off'}},
 // Speaker validation intentionally rejects control characters.
 {files:['src/features/speech/TranscriptRecovery.tsx','src/features/speech/SpeakerTools.tsx','src/features/speech/Transcription.tsx'],rules:{'no-control-regex':'off'}},
);
