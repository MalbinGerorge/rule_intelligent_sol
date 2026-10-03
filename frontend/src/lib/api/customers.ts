import { apiGet } from './client';

export interface Customer {
	id: number;
	name: string;
}

export interface CustomerListResponse {
	customers: Customer[];
}

export function fetchCustomers(): Promise<CustomerListResponse> {
	return apiGet<CustomerListResponse>('/customers');
}