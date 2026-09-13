import {createContext,useContext} from 'react';

export type Theme='light'|'dark';
export const THEME_KEY='yue2-studio-theme-v1';
export function readTheme():Theme{
  try{return localStorage.getItem(THEME_KEY)==='light'?'light':'dark'}catch{return 'dark'}
}
export const ThemeContext=createContext<Theme>('dark');
export const useTheme=()=>useContext(ThemeContext);
