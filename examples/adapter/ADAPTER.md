# Adapter instructions

The model reads this file at Start and on every tick, next to the skill's SKILL.md. Write here
what is specific to your own system of record.

## Sources

Each MCP server and tool the model may read, and how a customer's records are found in it.
Reads only.

## Resolving a customer at Start

How to find a customer's contacts, their ids in each source, and their organization id.

## Trust facts

- `linkedin_connected`: how to tell, without spending scarce reads.
- Which items count as my own messages (`from_me`).
- Where usage and value come from.

## Drafting

The tool that creates a draft in each channel (email, chat, tickets), how to reply in a thread,
and how the signature gets added. A watch session never sends.

## Picture sources

Where a contact's photo and a company's logo come from, in order.

## Rules

What may never leave the ledger.
