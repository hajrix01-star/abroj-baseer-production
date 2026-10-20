/** Device-local storage authority, not ERP totals or a report of free disk space. */
export interface MediaCacheTotals { files:number;bytes:number;filesDisplay:string;bytesDisplay:string }
export interface MediaCacheOverview { total:MediaCacheTotals;protected:MediaCacheTotals;policy:{autoClean30Days:boolean} }
export interface MediaCacheCleanPlan { id:string;mode:'all'|'unused30';expiresAt:number;estimated:MediaCacheTotals }
export interface MediaCacheCleanResult { deleted:MediaCacheTotals;skipped:MediaCacheTotals;failed:MediaCacheTotals;partial:boolean }
export interface MediaOfflineState { kept:boolean;available:boolean }
export function mediaCacheTotals(files:number,bytes:number):MediaCacheTotals {
  if(!Number.isSafeInteger(files)||files<0||!Number.isSafeInteger(bytes)||bytes<0)throw new Error('invalid_media_cache');
  const divisor=bytes>=1024*1024?1024*1024:1024,unit=divisor===1024?'KiB':'MiB';
  const scaled=(BigInt(bytes)*100n+BigInt(divisor)/2n)/BigInt(divisor);
  return {files,bytes,filesDisplay:String(files),bytesDisplay:bytes<1024?`${bytes} B`:`${scaled/100n}.${String(scaled%100n).padStart(2,'0')} ${unit}`};
}
