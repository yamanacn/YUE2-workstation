import {Children,isValidElement,useId,type ReactNode} from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import {CaretDownIcon,CheckIcon} from './icons';

/** Shared themed single-choice menu; surrounding label also labels its button. */
export function SelectControl({value,onChange,children,disabled=false}:{value:string|number;onChange:(event:{target:{value:string}})=>void;children:ReactNode;disabled?:boolean}){
  const id=useId();
  const options=Children.toArray(children).filter(isValidElement<{value:string|number;children:ReactNode;disabled?:boolean}>).map(child=>({value:String(child.props.value),label:child.props.children,disabled:child.props.disabled}));
  const selected=options.find(option=>option.value===String(value));
  return <Menu.Root><Menu.Trigger asChild><button id={id} type="button" className="select-control" disabled={disabled}><span>{selected?.label}</span><CaretDownIcon size={16} aria-hidden="true"/></button></Menu.Trigger><Menu.Portal><Menu.Content className="select-menu" sideOffset={6} collisionPadding={12} align="start" aria-label="选择参数值"><Menu.RadioGroup value={String(value)} onValueChange={next=>onChange({target:{value:next}})}>{options.map(option=><Menu.RadioItem key={option.value} value={option.value} disabled={option.disabled} className="select-option"><span>{option.label}</span><Menu.ItemIndicator className="select-check"><CheckIcon size={15} weight="bold"/></Menu.ItemIndicator></Menu.RadioItem>)}</Menu.RadioGroup></Menu.Content></Menu.Portal></Menu.Root>;
}
