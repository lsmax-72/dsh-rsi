/** Host consumers need the complete catalog; the native APIs return one page. */
async function collectPages(read: (pagination: {limit:number;offset:number}) => Promise<{items:any[];total:number}>) {
  const items:any[]=[];
  for(let offset=0;;) {
    const page=await read({limit:50,offset});
    items.push(...page.items);offset+=page.items.length;
    if(offset>=page.total)return {items,total:items.length};
    if(!page.items.length)throw new Error('资产分页未返回剩余记录，请重试');
  }
}
export const listAllSkills=(core:any,input:any) => collectPages(pagination=>core.list({...input,pagination}));
export const listAllVersions=(core:any,input:any) => collectPages(pagination=>core.listVersions({...input,pagination}));
