import { openDatabaseAsync } from 'expo-sqlite';
import { SqliteArchiveStore } from './SqliteHistoryArchive';
import { compatibility } from '../compatibility';

// Private Android app database. No credentials and no claim of application-layer encryption.
// Lazy opening lets login/errors render if storage is unavailable; use never silently falls back.
export const historyArchive = new SqliteArchiveStore(() =>
  openDatabaseAsync(compatibility.storage.sqlite),
);
export const mediaCacheCatalog = historyArchive.mediaCacheCatalog;
