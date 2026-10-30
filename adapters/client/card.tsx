import React from 'react';
/** Reused header only needs Card/Body wrappers, not the panel's full component kit. */
export const Card=Object.assign(({children,className}:any)=><div className={`rsi-hub-header ${className??''}`}>{children}</div>,{Body:({children}:any)=><div>{children}</div>});
