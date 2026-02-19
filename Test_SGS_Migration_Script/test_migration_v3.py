#!/usr/bin/python3

"""
Copyright Koninklijke Philips N.V. 2025

All rights are reserved. Reproduction or transmission in whole or in part, in
any form or by any means, electronic, mechanical or otherwise, is prohibited
without the prior written consent of the copyright owner.
"""

import xml.etree.ElementTree as ET
import sys
import argparse
from io import StringIO


def mutate(xml_input):
    """Convert version 2 NetworkInterfaceConfig to version 3
    
    Args:
        xml_input: Either a file path (string) or XML content (string)
        
    Returns:
        str: The migrated XML as a string
    """
    # Try to parse as file path first, then as XML string
    try:
        # Check if it's a file path
        if xml_input.endswith('.xml') or '/' in xml_input or '\\' in xml_input:
            tree = ET.parse(xml_input)
        else:
            # Parse as XML string
            tree = ET.ElementTree(ET.fromstring(xml_input))
    except ET.ParseError:
        # If parsing as string fails, try as file path
        try:
            tree = ET.parse(xml_input)
        except:
            raise Exception('Invalid XML input: Could not parse as file or XML string')
    except FileNotFoundError:
        # If file not found, try parsing as XML string
        try:
            tree = ET.ElementTree(ET.fromstring(xml_input))
        except:
            raise Exception('File not found and invalid XML string provided')
    
    network_element = tree.getroot()
    if not network_element.tag == 'NetworkInterfaceConfig':
        raise Exception('Invalid XML input: NetworkInterfaceConfig element not found')

    network_interface_element = network_element.find('NetworkInterface')
    if network_interface_element is None:
        raise Exception('Invalid XML input: NetworkInterface element not found')

    # Update version
    network_element.set('version', '3')

    # Add Method element as first element if it doesn't exist
    method_element = network_element.find('Method')
    if method_element is None:
        method_element = ET.Element('Method')
        method_element.text = 'Manual'
        network_element.insert(0, method_element)

    static_network_element = network_interface_element.find('StaticNetworkConfig')
    if static_network_element is None:
        raise Exception('Invalid XML input: StaticNetworkConfig element not found - all fields are mandatory in version 2 NetworkInterfaceConfig')
    else:
        # Update IpAddress to IpV4Address if needed for v2 compatibility
        ip_element = static_network_element.find('IpAddress')
        if ip_element is not None:
            # Change tag name from IpAddress to IpV4Address
            ip_element.tag = 'IpV4Address'
        
        # Remove StaticNetworkConfig from NetworkInterface (we'll move it under Manual)
        network_interface_element.remove(static_network_element)

    # Remove MAC address from NetworkInterface if it exists (version 2 format)
    mac_element = network_interface_element.find('MacAddress')
    if mac_element is not None:
        network_interface_element.remove(mac_element)

    # Create Manual element and add StaticNetworkConfig under it
    manual_element = ET.Element('Manual')
    manual_element.append(static_network_element)
    network_interface_element.append(manual_element)

    # Return the updated XML as string with pretty formatting
    ET.indent(tree, space="    ")  # Add 4-space indentation
    output = StringIO()
    tree.write(output, encoding='unicode', xml_declaration=True)
    return output.getvalue()


def main():
    """Main function to handle command line arguments and process XML"""
    parser = argparse.ArgumentParser(description='Migrate NetworkInterfaceConfig from version 2 to version 3')
    parser.add_argument('input', nargs='?', help='Input XML file path or XML string (if not provided, reads from stdin)')
    parser.add_argument('-f', '--file', action='store_true', help='Force treat input as file path')
    parser.add_argument('-s', '--string', action='store_true', help='Force treat input as XML string')
    
    args = parser.parse_args()
    
    # Get input XML
    if args.input:
        xml_input = args.input
        if args.file:
            # Force file mode
            try:
                with open(xml_input, 'r', encoding='utf-8') as f:
                    xml_content = f.read()
                migrated_xml = mutate(xml_content)
            except FileNotFoundError:
                print(f"Error: File '{xml_input}' not found", file=sys.stderr)
                sys.exit(1)
        elif args.string:
            # Force string mode
            migrated_xml = mutate(xml_input)
        else:
            # Auto-detect
            migrated_xml = mutate(xml_input)
    else:
        # Read from stdin
        xml_input = sys.stdin.read().strip()
        if not xml_input:
            print("Error: No input provided", file=sys.stderr)
            sys.exit(1)
        migrated_xml = mutate(xml_input)
    
    # Print the migrated XML
    print(migrated_xml)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
