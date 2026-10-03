import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { OpportunityCard } from '../src/Opportunities';
import { Score } from '../src/ui';
export { api, safeUrl, numeric, date } from '../src/api';
export { activityTitle, activityDetail, chartSeries, compensationVisibility, healthSeries, eligibilityLabel, eligibilityTone } from '../src/presentation';
export { normalizeSearchFilters, opportunityQuery, parseSavedViews } from '../src/searchViews';
export const renderCard=(job:any)=>renderToStaticMarkup(<OpportunityCard job={job} compact/>);
export const renderScore=(value:any)=>renderToStaticMarkup(<Score value={value}/>);
