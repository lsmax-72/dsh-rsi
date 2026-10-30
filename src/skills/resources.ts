import { readdir,readFile,realpath,lstat } from 'node:fs/promises';
import { join,relative,sep } from 'node:path';
/** Import a bounded managed copy; never follow links or execute original scripts. */
export async function copyResources(base:any) {
  if (!base) return [];
  if (base.kind !== 'directory') throw new Error('当前只支持复制本地目录技能；远程资源需先下载为本地技能');
  const root=await realpath(base.path),files:any[]=[];let bytes=0;
  async function walk(path:string) {
    for (const entry of await readdir(path,{withFileTypes:true})) {
      if (['.git','node_modules','.env'].includes(entry.name)) continue;
      const absolute=join(path,entry.name),stat=await lstat(absolute);
      if (stat.isSymbolicLink()) throw new Error('技能资源包含符号链接，请先整理为独立文件');
      if (stat.isDirectory()) {await walk(absolute);continue;}
      if (!stat.isFile()) throw new Error('技能资源包含非普通文件');
      const local=relative(root,absolute).split(sep).join('/');if(local==='SKILL.md')continue;
      bytes+=stat.size;if(stat.size>8*1024*1024 || bytes>32*1024*1024 || files.length>=256)throw new Error('技能资源超过复制上限');
      const content=await readFile(absolute);files.push({path:local,content:content.toString('base64'),encoding:'base64',is_executable:!!(stat.mode&0o111)});
    }
  }
  await walk(root);return files;
}
export async function versionResources(core:any,skill:any) {
  const files=[];
  for (const file of skill.manifest ?? []) {const stored=await core.resources.readResource(skill.skill_id,skill.version,file.path,'base64');if (!stored)throw new Error(`版本资源缺失：${file.path}`);files.push({...stored,is_executable:file.is_executable});}
  return files;
}
